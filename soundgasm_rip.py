#! python3
import urllib.request
from urllib.parse import quote as url_quote
import re
import os
import time
import sys
import configparser
import logging
import logging.handlers
import base64
import argparse
import clipwatcher_single
import praw
import bs4
import pandas as pd
import timeit

# init ConfigParser instance
config = configparser.ConfigParser()
# read config file, ConfigParser pretty much behaves like a dict, sections in in ["Reddit"] is a key that holds
# another dict with keys(USER_AGENT etc.) and values -> nested dict -> access with config["Reddit"]["USER_AGENT"]
# !! keys in sections are case-insensitive and stored in lowercase
config.read("config.ini")

# init Reddit instance
reddit_praw = praw.Reddit(client_id=config["Reddit"]["CLIENT_ID"],
                          client_secret=config["Reddit"]["CLIENT_SECRET"],
                          user_agent=config["Reddit"]["USER_AGENT"])

# banned TAGS that will exclude the file from being downloaded (when using reddit)
# load from config ini, split at comma, strip whitespaces
KEYWORDLIST = [x.strip() for x in config["Settings"]["tag_filter"].split(",")]

# path to dir where the soundfiles will be stored in subfolders
ROOTDIR = os.path.abspath(os.path.join(os.getcwd(), os.pardir))

DLTXT_ENTRY_END = "\t" + ("___" * 30) + "\n\n\n"

# configure logging
# logfn = time.strftime("%Y-%m-%d.log")
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# create a file handler
handler = logging.handlers.TimedRotatingFileHandler("gwaripper.log", "D", encoding="UTF-8", backupCount=10)
handler.setLevel(logging.DEBUG)

# create a logging format
formatter = logging.Formatter("%(asctime)-15s - %(name)-9s - %(levelname)-6s - %(message)s")
# '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
handler.setFormatter(formatter)

# add the handlers to the logger
logger.addHandler(handler)

# create streamhandler
stdohandler = logging.StreamHandler(sys.stdout)
stdohandler.setLevel(logging.INFO)

# create a logging format
formatterstdo = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", "%H:%M:%S")
stdohandler.setFormatter(formatterstdo)
logger.addHandler(stdohandler)

# we dont have to re-load while still running since it gets appended and then reassigned and
# SGR_DF survives main() starting again

# load dataframe
# SGR_DF = pd.read_json("../sgasm_rip_db.json", orient="columns")
SGR_DF = pd.read_csv("../sgasm_rip_db.csv", sep=";", encoding="utf-8", index_col=0)
GRPED_DF = SGR_DF.groupby("sgasm_user")


def main():
    parser = argparse.ArgumentParser(description="Script to download gonewildaudio/pta posts from either reddit "
                                                 "or soundgasm.net directly.")
    # support sub-commands like svn checkout which require different kinds of command-line arguments
    subparsers = parser.add_subparsers(title='subcommands', description='valid subcommands', help='sub-command help')

    # process single links by default # nargs="*" -> zero or more arguments
    # !! -> doesnt work since we need to specify a subcommand since they work like positional arguements
    # and providing a default subcommand isnt supported atm
    # create the parser for the "links" subcommand
    parser_lnk = subparsers.add_parser('links', help='Process single link/s')
    parser_lnk.add_argument("links", help="Links to process. Provide type of links as flag!", nargs="+")
    # argparse will make sure that only one of the arguments in the mutually exclusive group was present
    # also accepts a required argument, to indicate that at least one of the mutually exclusive arguments is required
    group_lnk = parser_lnk.add_mutually_exclusive_group(required=True)
    # store_true sets args.watchsgasm to true if flag is passed
    group_lnk.add_argument("-sg", "--sglinks", help="Rip from single sgasm link/s", action="store_true")
    group_lnk.add_argument("-r", "--reddit", help="Rip supported links from given reddit link/s.", action="store_true")
    # set funct to call when subcommand is used
    parser_lnk.set_defaults(func=cl_link)

    parser_usr = subparsers.add_parser('ripuser', help='Rip sgasm or reddit user/s')
    # nargs="+" -> one or more arguments
    parser_usr.add_argument("names", help="Names of users to rip.", nargs="+")
    # TODO Cleanup from argparse doc: Required options are generally considered bad form because users expect
    # options to be optional, and thus they should be avoided when possible.
    parser_usr.add_argument("-ty", "--type", required=True, choices=("sgasm", "reddit"),
                            help="Type of user: soundgasm.net user or redditor")
    # choices -> available options -> error if not contained; default -> default value if not supplied
    parser_usr.add_argument("-s", "--sort", choices=("hot", "top", "new"), default="top",
                            help="Reddit post sorting method")
    parser_usr.add_argument("-l", "--limit", type=int, required=True, help="How many posts to download")
    parser_usr.add_argument("-t", "--timefilter", help="Value for time filter", default="all",
                            choices=("all", "day", "hour", "month", "week", "year"))
    parser_usr.set_defaults(func=cl_ripuser)
    # we could set a function to call with these args parser_foo.set_defaults(func=foo)
    # call with args.func(args) -> let argparse handle which func to call instead of long if..elif
    # However, if it is necessary to check the name of the subparser that was invoked, the dest keyword argument
    # to the add_subparsers(): parser.add_subparsers(dest='subparser_name')
    # Namespace(subparser_name='ripuser', ...)

    parser_txt = subparsers.add_parser('fromtxt', help='Process links in txt file located in _linkcol')
    group_txt = parser_txt.add_mutually_exclusive_group(required=True)

    parser_txt.add_argument("filename", help="Filename of txt file in _linkcol folder. Specify type of links"
                                             "with flag!")
    group_txt.add_argument("-sgt", "--sgfromtxt", help="File with given filename contains sgasm links!",
                           action="store_true")
    group_txt.add_argument("-rt", "--reddittxt", help="File with given filename contains reddit links!",
                           action="store_true")
    parser_txt.set_defaults(func=cl_fromtxt)

    parser_clip = subparsers.add_parser('watch', help='Watch clipboard for sgasm/reddit links and save them to txt;'
                                                      ' option to process them immediately')
    parser_clip.add_argument("type", help="Type of links to watch for", choices=("sgasm", "reddit"))
    parser_clip.set_defaults(func=cl_watch)

    # provide shorthands or alt names with aliases
    parser_sub = subparsers.add_parser('subreddit', aliases=["sub"],
                                       help='Parse subreddit and download supported links')

    parser_sub.add_argument("sub", help="Name of subreddit")
    parser_sub.add_argument("-s", "--sort", choices=("hot", "top"), help="Reddit post sorting method",
                            default="top")
    parser_sub.add_argument("-l", "--limit", type=int, help="How many posts to download", required=True)
    parser_sub.add_argument("-t", "--timefilter", help="Value for time filter", default="all",
                            choices=("all", "day", "hour", "month", "week", "year"))
    parser_sub.set_defaults(func=cl_sub)

    parser_se = subparsers.add_parser('search', help='Search subreddit and download supported links')
    # parser normally uses name of dest=name (which u use to access value with args.name) var for refering to
    # argument -> --subreddit SUBREDDIT; can be different from option string e.g. -user, dest="name"
    # can be changed with metavar, when nargs=n -> tuple with n elements
    # bug in argparse: http://bugs.python.org/issue14074
    # no tuples allowed as metavars for positional arguments
    # it works with a list but the help output is wrong:
    # on usage it uses 2x['SUBREDDIT', 'SEARCHSTRING'] instead of SUBREDDIT SEARCHSTRING
    # with a tuple and as optional arg it works correctly: [-subsearch SUBREDDIT SEARCHSTRING]
    # but fails with a list: on opt arg line as well
    # [-subsearch ['SUBREDDIT', 'SEARCHSTRING'] ['SUBREDDIT', 'SEARCHSTRING']]
    # only uniform positional arguments allowed basically as in: searchstring searchstring...
    # always of the same kind
    # metavar=['SUBREDDIT', 'SEARCHSTRING'])
    parser_se.add_argument("subname", help="Name of subreddit")
    parser_se.add_argument("sstr", help="'searchstring' in QUOTES: https://www.reddit.com/wiki/search",
                           metavar="searchstring")
    parser_se.add_argument("-s", "--sort", choices=("hot", "top"), help="Reddit post sorting method",
                           default="top")
    parser_se.add_argument("-l", "--limit", type=int, help="How many posts to download", required=True)
    parser_se.add_argument("-t", "--timefilter", help="Value for time filter", default="all",
                           choices=("all", "day", "hour", "month", "week", "year"))
    parser_se.set_defaults(func=cl_search)

    parser.add_argument("-te", "--test", action="store_true")

    # check with: if not len(sys.argv) > 1
    # if no arguments were passed and call our old input main func; or use argument with default value args.old
    if not len(sys.argv) > 1:
        print("No arguments passed! Call this script from the command line with -h to show available commands.")
        argv_str = input("Simulating command line input!!\n\nType in command line args:\n").split()

        # simulate shell/cmd way of considering strings with spaces in quotation marks as one single arg/string
        argv_clean = []
        # index of element in list with first quotation mark
        first_i = None
        # iterate over list, keeping track of index with enumerate
        for i, s in enumerate(argv_str):
            # found quotation mark and were not currently looking for the end of a quote (first_i not set)
            # ("\"" in s) or ("\'" in s) and not first_i needs to be in extra parentheses  or it will be evaluated like:
            # True | (False & False) -> True, since only ("\'" in s) and not first_i get connected with and
            # (("\"" in s) or ("\'" in s)) and not first_i:
            # (This OR This must be true) AND not This must be false
            if (("\"" in s) or ("\'" in s)) and not first_i:
                # the whole quote is in this element of the list
                if (s.count("\"") > 1) or (s.count("\'") > 1):
                    # strip away quot marks and append
                    argv_clean.append(s.strip("\"").strip("\'"))
                    continue
                else:
                    # save index
                    first_i = i
                    # continue with next element in list
                    continue
            # found quotation mark and were currently looking for the end of a quote (first_i set)
            elif (("\"" in s) or ("\'" in s)) and first_i:
                # get slice of list from index of first quot mark to this index: argv_str[first_i:i+1]
                # due to how slicing works we have to +1 the current i
                # join the slice with spaces to get the spaces back: " ".join()
                # get rid of quot marks with strip("\"")
                # append str to clean list
                argv_clean.append(" ".join(argv_str[first_i:i+1]).strip("\""))
                # unset first_i
                first_i = None
                continue
            elif not first_i:
                # normal element of list -> append to clean list
                argv_clean.append(s)

        # simulate command line input by passing in list like: ['--sum', '7', '-1', '42']
        # which is the same as prog.py --sum 7 -1 42 -> this is also used in docs of argparse
        args = parser.parse_args(argv_clean)
    else:
        # parse_args() will only contain attributes for the main parser and the subparser that was selected
        args = parser.parse_args()

    if args.test:
        # test code
        print("test")
    else:
        # call func that was selected for subparser/command
        args.func(args)


def cl_link(args):
    if args.sglinks:
        llist = gen_audiodl_from_sglink(args.links)
        rip_audio_dls(llist)
    else:
        llist = get_sub_from_reddit_urls(args.links)
        adl_list = parse_submissions_for_links(llist)
        rip_audio_dls(adl_list)


def cl_ripuser(args):
    if args.type == "sgasm":
        rip_users(*args.names)
    else:
        sort = args.sort
        limit = args.limit
        time_filter = args.timefilter
        for usr in args.names:
            redditor = reddit_praw.redditor(usr)
            if sort == "hot":
                sublist = redditor.submissions.hot(limit=limit)
            elif sort == "top":
                sublist = redditor.submissions.top(limit=limit, time_filter=time_filter)
            else:  # just get new posts if input doesnt match hot or top
                sublist = redditor.submissions.new(limit=limit)
            # TODO Refactor check if subreddit is gwa or pta first?
            adl_list = parse_submissions_for_links(sublist)
            if adl_list:
                rip_audio_dls(adl_list)
            else:
                logger.warning("No subs recieved from user {} with time_filter {}".format(usr, args.timefilter))


def cl_fromtxt(args):
    mypath = os.path.join(ROOTDIR, "_linkcol")
    if args.sgfromtxt:
        rip_audio_dls(gen_audiodl_from_sglink(txt_to_list(mypath, args.filename)))
    else:
        llist = get_sub_from_reddit_urls(txt_to_list(mypath, args.filename))
        adl_list = parse_submissions_for_links(llist, True)
        rip_audio_dls(adl_list)


def cl_watch(args):
    if args.type == "sgasm":
        found = watch_clip("sgasm")
        if found:
            llist = gen_audiodl_from_sglink(found)
            rip_audio_dls(llist)
    else:
        found = watch_clip("reddit")
        if found:
            llist = get_sub_from_reddit_urls(found)
            adl_list = parse_submissions_for_links(llist, True)
            rip_audio_dls(adl_list)


def cl_sub(args):
    sort = args.sort
    limit = args.limit
    time_filter = args.timefilter
    if sort == "top":
        adl_list = parse_submissions_for_links(parse_subreddit(args.sub, sort, limit, time_filter=time_filter))
    else:
        # fromtxt False -> check lastdltime against submission date of posts when dling from hot posts
        adl_list = parse_submissions_for_links(parse_subreddit(args.sub, sort, limit), fromtxt=False)
        write_last_dltime()
    rip_audio_dls(adl_list)


def cl_search(args):
    sort = args.sort
    limit = args.limit
    time_filter = args.timefilter

    found_subs = search_subreddit(args.subname, args.sstr, limit=limit, time_filter=time_filter,
                                  sort=sort)
    adl_list = parse_submissions_for_links(found_subs, True)
    if adl_list:
        rip_audio_dls(adl_list)
    else:
        logger.warning("No matching subs/links found in {}, with: '{}'".format(args.subname, args.sstr))


class AudioDownload:
    def __init__(self, page_url, host, reddit_info=None):
        self.page_url = page_url
        self.host = host
        self.reddit_info = reddit_info
        # use reddit user name if not sgasm
        if host == "sgasm":
            self.name_usr = self.page_url.split("/u/", 1)[1].split("/", 1)[0]
        else:
            self.name_usr = self.reddit_info["r_user"]
        self.downloaded = False
        self.url_to_file = None
        self.file_type = None
        self.title = None
        self.filename_local = None
        self.descr = None
        self.date = None
        self.time = None

    def call_host_get_file_info(self):
        if self.host == "sgasm":
            self.set_sgasm_info()
        elif self.host == "chirb.it":
            self.set_chirbit_url()
        elif self.host == "eraudica":
            self.set_eraudica_info()

    def set_chirbit_url(self):
        site = urllib.request.urlopen(self.page_url)
        html = site.read().decode('utf-8')
        site.close()
        soup = bs4.BeautifulSoup(html, "html.parser")

        # selects ONE i tag with set data-fd attribute beneath tag with class .wavholder beneath div with id main
        # then get attribute data-fd
        str_b64 = soup.select_one('div#main .wavholder i[data-fd]')["data-fd"]
        # reverse string using a slice -> string[start:stop:step], going through whole string with step -1 -> reverse
        str_b64_rev = str_b64[::-1]
        # decode base64 string to get url to file -> returns byte literal -> decode with appropriate encoding
        # this link EXPIRES so get it right b4 downloading
        self.url_to_file = base64.b64decode(str_b64_rev).decode("utf-8")
        self.file_type = self.url_to_file.split("?")[0][-4:]
        self.filename_local = re.sub("[^\w\-_\.,\[\] ]", "_", self.reddit_info["title"][0:110]) + self.file_type

    def set_eraudica_info(self):
        site = urllib.request.urlopen(self.page_url)
        html = site.read().decode('utf-8')
        site.close()
        soup = bs4.BeautifulSoup(html, "html.parser")

        # selects script tags beneath div with id main and div class post
        # returns list of bs4.element.Tag -> access text with .text
        scripts = soup.select("div#main div.post script")[1].text
        # vars that are needed to gen dl link are included in script tag
        # access group of RE (part in '()') with .group(index)
        # Group 0 is always present; it’s the whole RE
        fname = re.search("var filename = \"(.+)\"", scripts).group(1)
        server = re.search("var playerServerURLAuthorityIncludingScheme = \"(.+)\"", scripts).group(1)
        dl_token = re.search("var downloadToken = \"(.+)\"", scripts).group(1)
        # convert fname to make it url safe with urllib.quote (quote_plus replaces spaces with plus signs)
        fname = url_quote(fname)  # renamed so i dont accidentally create a func with same name

        self.url_to_file = "{}/fd/{}/{}".format(server, dl_token, fname)
        self.file_type = fname[-4:]
        self.filename_local = re.sub("[^\w\-_\.,\[\] ]", "_", self.reddit_info["title"][0:110]) + self.file_type

    def set_sgasm_info(self):
        # TODO Temporary? check if we alrdy called this so we dont call it twice when we call it to fill
        # in missing information in the SGR_DF
        if not self.url_to_file:
            logger.info("Getting soundgasm info of: %s" % self.page_url)
            try:
                site = urllib.request.urlopen(self.page_url)
                html = site.read().decode('utf-8')
                site.close()
                nhtml = html.split("aria-label=\"title\">")
                title = nhtml[1].split("</div>", 1)[0]
                # descript = nhtml[1].split("Description: ")[1].split("</li>\r\n", 1)[0]
                descript = \
                    nhtml[1].split("<div class=\"jp-description\">\r\n          <p style=\"white-space: pre-wrap;\">")[
                        1].split(
                        "</p>\r\n", 1)[0]
                urlm4a = nhtml[1].split("m4a: \"")[1].split("\"\r\n", 1)[0]
                # set instance values
                self.url_to_file = urlm4a
                self.file_type = ".m4a"
                self.title = title
                self.filename_local = re.sub("[^\w\-_\.,\[\] ]", "_", title[0:110]) + ".m4a"
                self.descr = descript
            except urllib.request.HTTPError:
                logger.warning("HTTP Error 404: Not Found: \"%s\"" % self.page_url)

    def download(self, curfnr, maxfnr):
        if self.url_to_file is not None:
            curfnr += 1

            filename = self.filename_local
            mypath = os.path.join(ROOTDIR, self.name_usr)
            if not os.path.exists(mypath):
                os.makedirs(mypath)
            i = 0
            # Actually it is considered better practice to try and open the file with a try-except block, than
            # to check for existence – jarondl Jul 6 '13 at 12:45 3
            # @jarondl is right. This should be changed to use a try: ... except IOError to avoid potential race
            # conditions. For most cases it won't matter but this has bitten me recently
            if os.path.isfile(os.path.join(mypath, filename)):
                if check_direct_url_for_dl(self.url_to_file, self.name_usr):
                    set_missing_values_df(SGR_DF, self)
                    logger.warning("!!! File already exists and was found in direct urls but not in sg_urls!\n"
                                   "--> not renaming --> SKIPPING")
                    return curfnr
                else:
                    logger.info("FILE ALREADY EXISTS - RENAMING:")
                    # file alrdy exists but it wasnt in the url databas -> prob same titles only one tag
                    # or the ending is different (since fname got cut off, so we dont exceed win path limit)
                    # count up i till file doesnt exist anymore
                    while os.path.isfile(os.path.join(mypath, filename)):
                        i += 1
                        # TODO Refactor get rid of ending in filename?
                        filename = self.filename_local[:-4] + "_" + str(i).zfill(3) + self.file_type
                    # set filename on AudioDownload instance
                    self.filename_local = filename

            logger.info("Downloading: " + filename + ", File " + str(curfnr) + " of " + str(maxfnr))
            self.date = time.strftime("%d/%m/%Y")
            self.time = time.strftime("%H:%M:%S")
            # set downloaded
            self.downloaded = True

            try:
                urllib.request.urlretrieve(self.url_to_file, os.path.abspath(os.path.join(mypath, filename)))
            except urllib.request.HTTPError:
                # dl failed set downloaded
                self.downloaded = False
                logger.warning("HTTP Error 404: Not Found: \"%s\"" % self.url_to_file)

            if self.reddit_info:
                # also write reddit selftext in txtfile with same name as audio
                self.write_selftext_file()

            return curfnr
        else:
            logger.warning("FILE DOWNLOAD SKIPPED - NO DATA RECEIVED")
            return curfnr

    def write_selftext_file(self):
        if self.reddit_info["selftext"]:
            # write_to_txtf uses append mode, but we'd have the selftext several times in the file since
            # there are reddit posts with multiple sgasm files
            # write_to_txtf(self.reddit_info["selftext"], self.filename_local + ".txt", self.name_usr)
            mypath = os.path.join(ROOTDIR, self.name_usr)
            if not os.path.exists(mypath):
                os.makedirs(mypath)
            # if selftext file doesnt already exists
            if not os.path.isfile(os.path.join(mypath, self.filename_local + ".txt")):
                with open(os.path.join(mypath, self.filename_local + ".txt"), "w", encoding="UTF-8") as w:
                    w.write(self.reddit_info["selftext"])


def rip_users(*users):
    for usr in users:
        # geht jede url in der liste durch entfernt das komma und gibt sie an rip_usr_to_files weiter
        rip_usr_to_files(usr)


def txt_to_list(path, txtfilename):
    with open(os.path.join(path, txtfilename), "r", encoding="UTF-8") as f:
        llist = f.read().split()
        return llist


def get_sub_from_reddit_urls(urllist):
    urls_unique = set(urllist)
    sublist = []
    for url in urls_unique:
        sublist.append(reddit_praw.submission(url=url))
    return sublist


# avoid too many function calls since they are expensive in python
def gen_audiodl_from_sglink(sglinks):
    dl_list = []
    for link in sglinks:
        a = AudioDownload(link, "sgasm")
        dl_list.append(a)
    return dl_list


def rip_audio_dls(dl_list, current_usr=None):
    """
    Accepts list of AudioDownload instances and filters them for new downloads and saves them to disk by
    calling download method
    :param dl_list: List of AudioDownload instances
    :param current_usr: name of user when called from rip_usr_to_files
    """
    # when assigning instance Attributs of classes like self.url
    # Whenever we assign or retrieve any object attribute like url, Python searches it in the object's
    # __dict__ dictionary -> Therefore, a_file.url internally becomes a_file.__dict__['url'].
    # could just work with dicts instead since theres no perf loss, but using classes may be easier to
    # implement new featueres

    # create dict that has direct links to files as keys and AudioDownload instances as values
    dl_dict = {}
    for audio in dl_list:
        dl_dict[audio.page_url] = audio

    # returns list of new downloads, dl_dict still holds all of them
    new_dls = filter_alrdy_downloaded(dl_dict, current_usr)

    filestodl = len(new_dls)
    dlcounter = 0

    for url in new_dls:
        audio_dl = dl_dict[url]
        # get appropriate func for host to get direct url, sgasm title etc.
        audio_dl.call_host_get_file_info()

        dlcounter = audio_dl.download(dlcounter, filestodl)

    if new_dls:
        # write info of new downloads to SGR_DF
        append_new_info_downloaded(new_dls, dl_dict)
    elif dl_list[0].reddit_info:
        # TODO Temporary we might have set missing info on already downloaded files so new_dls might
        # be None even if we added info to df so always safe it to be sure
        # or do elif dl_list[0].reddit_info -> ripping from reddit links so we wrote missing info
        # if we didnt dl sth new
        SGR_DF.to_csv("../sgasm_rip_db.csv", sep=";", encoding="utf-8")
        SGR_DF.to_json("../sgasm_rip_db.json")

    return dlcounter


def append_new_info_downloaded(new_dl_list, dl_dict):
    # filenr missing
    df_append_dict = {"Date": [], "Time": [], "Local_filename": [], "Description": [], "Title": [], "URL": [],
                      "URLsg": [], "sgasm_user": [], "redditURL": [], "reddit_user": [], "redditTitle": [],
                      "created_utc": [], "redditID": [], "subredditName": [], "rPostUrl": []}

    reddit_set_helper = (("redditTitle", "title"), ("redditURL", "permalink"), ("reddit_user", "r_user"),
                         ("created_utc", "created_utc"), ("redditID", "id"), ("subredditName", "subreddit"),
                         ("rPostUrl", "r_post_url"))

    for url in new_dl_list:
        audio_dl = dl_dict[url]

        if audio_dl.downloaded:
            df_append_dict["Date"].append(audio_dl.date)
            df_append_dict["Time"].append(audio_dl.time)
            df_append_dict["Local_filename"].append(audio_dl.filename_local)
            df_append_dict["Description"].append(audio_dl.descr)
            df_append_dict["Title"].append(audio_dl.title)
            df_append_dict["URL"].append(audio_dl.url_to_file)
            df_append_dict["URLsg"].append(audio_dl.page_url)
            df_append_dict["sgasm_user"].append(audio_dl.name_usr)

            # append all the reddit info if set
            if audio_dl.reddit_info:
                for col, r_dkey in reddit_set_helper:
                    df_append_dict[col].append(audio_dl.reddit_info[r_dkey])
            # make sure we write all the columns -> append "" or none as reddit info
            else:
                for col, r_dkey in reddit_set_helper:
                    df_append_dict[col].append("")

    # check if lists have equal length -> NOT -> ABORT!!
    # store length of one list in var to avoid overhead if accessing it in loop
    len_first = len(df_append_dict["Date"]) if df_append_dict else None
    # all returns true if all elements of iterable are true
    # dict.values() returns new view of dicts values, iter() returns an iterator over those items,
    # also works without iter()
    if not all(len(i) == len_first for i in iter(df_append_dict.values())):
        logger.error("ABORT !! Lists of append dict ARE NOT THE SAME SIZE !! ABORT !!")
        return
    elif len_first == 0:
        logger.info("No new downloads!")
        return

    df_dict = pd.DataFrame.from_dict(df_append_dict)
    # append to global SGR_DF
    global SGR_DF
    logger.info("Writing info of new downloads to Database!")
    SGR_DF = SGR_DF.append(df_dict, ignore_index=True, verify_integrity=True)
    SGR_DF.to_csv("../sgasm_rip_db.csv", sep=";", encoding="utf-8")
    SGR_DF.to_json("../sgasm_rip_db.json")

    # update groupby obj
    global GRPED_DF
    GRPED_DF = SGR_DF.groupby("sgasm_user")

    # auto backup
    backup_db()


def rip_usr_to_files(currentusr):
    sgasm_usr_url = "https://soundgasm.net/u/{}".format(currentusr)
    logger.info("Ripping user %s" % currentusr)

    dl_list = gen_audiodl_from_sglink(rip_usr_links(sgasm_usr_url))

    rip_audio_dls(dl_list, currentusr)


# # keep track if we alrdy warned the user
# warned = False
#
# # filestodl decreased by one if a file gets skipped
# if erg[1] != filestodl:
#     skipped_file_counter += 1
# # if the same -> not consecutive -> set to zero
# else:
#     skipped_file_counter = 0
#
# # since new audios show up on the top on sgasm user page and rip_usr_links() writes them to a list
# # from top to bottom -> we can assume the first links we dl are the newest posts
# # -> too many CONSECUTIVE Files already downloaded -> user_rip is probably up-to-date
# # ask if we should continue for the offchance of having downloaded >15--25 newer consecutive files
# # but not the old ones (when using single dl)
# if not warned and skipped_file_counter > 15:
#     option = input("Over 15 consecutive files already had been downloaded. Should we continue?\n"
#                    "y or n?: ")
#     if option == "n":
#         break
#     else:
#         warned = True

def rip_usr_links(sgasm_usr_url):
    site = urllib.request.urlopen(sgasm_usr_url)
    html = site.read().decode('utf-8')
    site.close()
    # links zu den einzelnen posts isolieren
    nhtml = html.split("<div class=\"sound-details\"><a href=\"")
    del nhtml[0]
    user_files = []
    for splits in nhtml:
        # teil str in form von https://soundgasm.net/u/USERNAME/link-to-post> an ">" und schreibt
        # den ersten teil in die variable url
        url = splits.split("\">", 1)[0]
        # url in die liste anfuegen
        user_files.append(url)
    filestodl = len(user_files)
    logger.info("Found " + str(filestodl) + " Files!!")
    return user_files


def set_missing_values_df(dframe, audiodl_obj):
    # get index of matching direct url in dframe
    index = dframe[dframe["URL"] == audiodl_obj.url_to_file].index[0]
    # fill_dict = {"Local filename": audiodl_obj.filename_local, "URLsg": audiodl_obj.page_url}
    # dframe.iloc[index, :].fillna(fill_dict, inplace=True)
    # isnull on row iloc[index] returns Series with True for null values
    # only np.nan pd.NaT or None are considered null by isnull()
    cell_null_bool = dframe.iloc[index].isnull()
    # if field isnull()
    if cell_null_bool["URLsg"]:
        # dframe["URLsg"][index] = audiodl_obj.page_url
        dframe.set_value(index, "URLsg", audiodl_obj.page_url)
    else:
        logger.warning("Field not set since it wasnt empty when trying to set "
                       "URLsg on row[{}] for {}".format(index, audiodl_obj.title))
    if cell_null_bool["Local_filename"]:
        dframe.set_value(index, "Local_filename", audiodl_obj.filename_local)
    else:
        logger.warning("Field not set since it wasnt empty when trying to set Local filename "
                       "on row for {}[{}]".format(audiodl_obj.title, index))

    # also set reddit info if available
    if audiodl_obj.reddit_info:
        set_helper = (("redditTitle", "title"), ("redditURL", "permalink"), ("reddit_user", "r_user"),
                      ("created_utc", "created_utc"), ("redditID", "id"), ("subredditName", "subreddit"),
                      ("rPostUrl", "r_post_url"))
        # iterate over set_helper unpacking col name and dictkey of audiodl_obj.reddit_info
        for col, dictkey in set_helper:
            if cell_null_bool[col]:
                dframe.set_value(index, col, audiodl_obj.reddit_info[dictkey])
            else:
                logger.warning("Field not set since it wasnt empty when trying to set {} "
                               "on row for {}[{}]".format(col, audiodl_obj.title, index))

        # write selftext if there's reddit info
        audiodl_obj.write_selftext_file()


def write_to_txtf(wstring, filename, currentusr):
    mypath = os.path.join(ROOTDIR, currentusr)
    if not os.path.exists(mypath):
        os.makedirs(mypath)
    with open(os.path.join(mypath, filename), "a", encoding="UTF-8") as w:
        w.write(wstring)


def check_direct_url_for_dl(direct_url, current_usr=None):
    """
    Returns True if file was already downloaded
    :param direct_url: direct URL to m4a file
    :param current_usr: User when doing full user rip
    :return: True if m4aurl is in SGR_DF in col URL, else False
    """
    if current_usr:
        try:
            if direct_url in GRPED_DF.get_group(current_usr)["URL"].values:
                return True
            else:
                return False
        except KeyError:
            logger.info("User '{}' not yet in databas!".format(current_usr))
            return False
    else:
        if direct_url in SGR_DF["URL"].values:
            return True
        else:
            return False


def filter_alrdy_downloaded(dl_dict, currentusr=None):
    # OLD when passing 2pair tuples, unpack tuples in dl_list into two lists
    # url_list, title = zip(*dl_list)
    # filter dupes
    unique_urls = set(dl_dict.keys())
    if currentusr:
        try:
            duplicate = unique_urls.intersection(GRPED_DF.get_group(currentusr)["URLsg"].values)
        except KeyError:
            logger.info("User '{}' not yet in databas!".format(currentusr))
            duplicate = set()
    else:
        # timeit 1000: 0.19
        duplicate = unique_urls.intersection(SGR_DF["URLsg"].values)

    dup_titles = ""
    # OLD when passing 2pair tuples -> create dict from it, NOW passing ref to dict
    # next -> Retrieve the next item from the iterator by calling its next() method.
    # iterates over list till it finds match, list comprehension would iterate over whole list
    # timeit: 0.4678
    # for a, b in dl_list -> iterates over dl_list unpacking the tuples
    # returns b if a == url
    # for url in duplicate:
    #     dup_titles += next(b for a, b in dl_list if a == url) + "\n"

    # dl_list is list of 2-tuples (2elements) -> basically key-value-pairs
    # -> turn into dict with dict(), this method(same string concat): 0.4478
    # d = dict(dl_list)
    for dup in duplicate:
        dup_titles += " ".join(dl_dict[dup].page_url[24:].split("-")) + "\n"
        # TODO Temporary
        # when we got reddit info get sgasm info even if this file was already downloaded b4
        # then write missing info to SGR_DF and write selftext to file
        if dl_dict[dup].reddit_info and ("soundgasm" in dup):
            logger.info("Filling in missing reddit info: TEMPORARY")
            dl_dict[dup].set_sgasm_info()
            set_missing_values_df(SGR_DF, dl_dict[dup])
            dl_dict[dup].write_selftext_file()
    if dup_titles:
        logger.info("{} files were already downloaded: \n{}".format(len(duplicate), dup_titles))

    # set.symmetric_difference()
    # Return a new set with elements in either the set or other but not both.
    # -> duplicates will get removed from unique_urls
    result = list(unique_urls.symmetric_difference(duplicate))
    # str.contains accepts regex patter, join url strings with | -> htt..m4a|htt...m4a etc
    # returns Series/array of boolean values, .any() True if any element is True
    # timeit 1000: 1.129
    # mask = SGR_DF["URL"].str.contains('|'.join(url_list))
    # isin also works
    # timeit 1000: 0.29
    # mask = SGR_DF["URL"].isin(unique_urls)
    # print(SGR_DF["URL"][mask])

    return result


def watch_clip(domain):
    # function is_domain_url will be predicate
    # eval: string -> python code
    dm = eval("clipwatcher_single.is_" + domain + "_url")
    watcher = clipwatcher_single.ClipboardWatcher(dm, clipwatcher_single.print_write_to_txtf, 0.1)
    try:
        logger.info("Watching clipboard...")
        watcher.run()
    except KeyboardInterrupt:
        watcher.stop()
        logger.info("Stopped watching clipboard!")
        logger.info("URLs were saved in: {}\n".format(watcher.txtname))
        yn = input("Do you want to download found URLs directly? (yes/no):\n")
        if yn == "yes":
            # dont return ref so watcher can die
            return watcher.found.copy()
        else:
            return


def parse_subreddit(subreddit, sort, limit, time_filter=None):
    sub = reddit_praw.subreddit(subreddit)
    if sort == "hot":
        return sub.hot(limit=limit)
    elif sort == "top":
        return sub.top(time_filter=time_filter, limit=limit)
    else:
        logger.warning("Sort must be either 'hot' or 'top'!")
        main()


def search_subreddit(subname, searchstring, limit=100, sort="top", **kwargs):
    # sort: relevance, hot, top, new, comments (default: relevance).
    # syntax: cloudsearch, lucene, plain (default: lucene) in praw4 cloud
    # time_filter – Can be one of: all, day, hour, month, week, year (default: all)
    subreddit = reddit_praw.subreddit(subname)

    found_sub_list = []
    # Returns a generator for submissions that match the search query
    matching_sub_gen = subreddit.search(searchstring, sort=sort, limit=limit,
                                        syntax="lucene", **kwargs)
    # iterate over generator and append found submissions to list
    for sub in matching_sub_gen:
        found_sub_list.append(sub)
    return found_sub_list


# If you have a PRAW object, e.g., Comment, Message, Redditor, or Submission, and you want to see what
# attributes are available along with their values, use the built-in vars() function of python
# import pprint
#
# # assume you have a Reddit instance bound to variable `reddit`
# submission = reddit.submission(id='39zje0') # lazy object -> fewer attributes than expected
# print(submission.title) # to make it non-lazy
# pprint.pprint(vars(submission))
# PRAW uses lazy objects so that network requests to Reddit’s API are only issued when information is needed
# When we try to print its title, additional information is needed, thus a network request is made, and the
# instances ceases to be lazy. Outputting all the attributes of a lazy object will result in fewer attributes
# than expected.


# deactivted LASTDLTIME check by default
def parse_submissions_for_links(sublist, fromtxt=True):
    dl_list = []
    if not fromtxt:
        # get new lastdltime from cfg
        reload_config()
    # all values stored as strings, configparser wont convert automatically so we do it with float(config[]..)
    # or use provided getfloat, getint method
    # provide fallback value if key isnt available
    # also works on parser-level if section (here: Time) isnt present:
    # float(config.get('Time', 'last_dl_time', fallback='0.0'))
    # configparser provides also a legacy API with explicit get/set methods. While there are valid use cases for the
    # methods outlined below, mapping protocol access is preferred for new projects
    # -> when we dont need fallback value use config["Time"]["last_dl_time"] etc.
    lastdltime = config.getfloat("Time", "last_dl_time", fallback=0.0)
    for submission in sublist:

        if (not check_submission_banned_tags(submission, KEYWORDLIST) and
                (fromtxt or check_submission_time(submission, lastdltime))):

            found_urls = []
            sub_url = submission.url
            # TODO Refactor make this more automated by checking for list of supported hosts or sth.
            if "soundgasm.net" in sub_url:
                found_urls.append(("sgasm", sub_url))
                logger.info("SGASM link found in URL of: " + submission.title)
            elif "chirb.it/" in sub_url:
                found_urls.append(("chirb.it", sub_url))
                logger.info("chirb.it link found in URL of: " + submission.title)
            elif "eraudica.com/" in sub_url:
                # remove gwa so we can access dl link directly
                if sub_url.endswith("/gwa"):
                    found_urls.append(("eraudica", sub_url[:-4]))
                else:
                    found_urls.append(("eraudica", sub_url))
                logger.info("eraudica link found in URL of: " + submission.title)
            elif submission.selftext_html is not None:
                soup = bs4.BeautifulSoup(submission.selftext_html, "html.parser")

                # selftext_html is not like the normal it starts with <div class="md"..
                # so i can just go through all a
                # css selector -> tag a with set href attribute
                sgasmlinks = soup.select('a[href]')
                usrcheck = re.compile("/u/.+/.+", re.IGNORECASE)

                for link in sgasmlinks:
                    href = link["href"]
                    # make sure we dont get an user link
                    if ("soundgasm.net" in href) and usrcheck.search(href):
                        # appends href-attribute of tag object link
                        found_urls.append(("sgasm", href))
                        logger.info("SGASM link found in text, in submission: " + submission.title)
                    elif "chirb.it/" in href:
                        found_urls.append(("chirb.it", href))
                        logger.info("chirb.it link found in text, in submission: " + submission.title)
                    elif "eraudica.com/" in href:
                        # remove gwa so we can access dl link directly
                        if href.endswith("/gwa"):
                            found_urls.append(("eraudica", href[:-4]))
                        else:
                            found_urls.append(("eraudica", href))
                        logger.info("eraudica link found in text, in submission: " + submission.title)
            else:
                logger.info("No soundgsam link in \"" + submission.shortlink + "\"")
                with open(os.path.join(ROOTDIR, "_linkcol", "reddit_nurl_" + time.strftime("%Y-%m-%d_%Hh.html")),
                          'a', encoding="UTF-8") as w:
                    w.write("<h3><a href=\"https://reddit.com{}\">{}</a><br/>by {}</h3>\n".format(submission.permalink,
                                                                                                  submission.title,
                                                                                                  submission.author))
            reddit_info = {"title": submission.title, "permalink": str(submission.permalink),
                           "selftext": submission.selftext, "r_user": submission.author.name,
                           "created_utc": submission.created_utc, "id": submission.id,
                           "subreddit": submission.subreddit.display_name, "r_post_url": sub_url}

            # create AudioDownload from found_urls
            for host, url in found_urls:
                dl_list.append(AudioDownload(url, host, reddit_info=reddit_info))

    return dl_list


def check_submission_banned_tags(submission, keywordlist):
    # checks submissions title for banned words contained in keywordlist
    # returns True if it finds a match
    subtitle = submission.title.lower()
    for keyword in keywordlist:
        if keyword in subtitle:
            logger.info("Banned keyword '{}' in: {}\n\t slink: {}".format(keyword, subtitle, submission.shortlink))
            return True
    # TODO Hardcode Hardcoding this is bad if someone else wants to use this script
    if ("[f4f]" in subtitle) and not ("4m]" in subtitle):
        logger.info("Banned keyword: no '4m]' in title where '[f4f]' is in: {}\n\t "
                    "slink: {}".format(subtitle, submission.shortlink))
        return True
    else:
        return False


def write_last_dltime():
    if config.has_section("Time"):
        config["Time"]["LAST_DL_TIME"] = str(time.time())
    else:
        # create section if it doesnt exist
        config["Time"] = {"LAST_DL_TIME": str(time.time())}
    with open("config.ini", "w") as config_file:
        # configparser doesnt preserve comments when writing
        config.write(config_file)


def reload_config():
    config.read("config.ini")


def backup_db(force_bu=False):
    bu_dir = os.path.join(ROOTDIR, "_db-autobu")
    if not os.path.exists(bu_dir):
        os.makedirs(bu_dir)
    # time.time() get utc number
    now = time.time()
    # freq in days convert to secs since utc time is in secs since epoch
    # get freq from config.ini use fallback value 3 days
    freq_secs = config.getint("Settings", "db_bu_freq", fallback=5) * 24 * 60 * 60
    elapsed_time = now - config.getfloat("Time", "last_db_bu", fallback=0.0)

    # if time since last db bu is greater than frequency in settings or we want to force a bu
    # time.time() is in gmt/utc whereas time.strftime() uses localtime
    if (elapsed_time > freq_secs) or force_bu:
        time_str = time.strftime("%Y-%m-%d")
        logger.info("Writing backup of database!")
        SGR_DF.to_csv("../_db-autobu/{}_sgasm_rip_db.csv".format(time_str), sep=";", encoding="utf-8")
        SGR_DF.to_json("../_db-autobu/{}_sgasm_rip_db.json".format(time_str))

        # update last db bu time
        if config.has_section("Time"):
            config["Time"]["last_db_bu"] = str(now)
        else:
            config["Time"] = {"last_db_bu": str(now)}
        # write config to file
        with open("config.ini", "w") as config_file:
            config.write(config_file)

        # iterate over listdir, add file to list if isfile returns true
        bu_dir_list = [os.path.join(bu_dir, f) for f in os.listdir(bu_dir) if os.path.isfile(os.path.join(bu_dir, f))]
        # we could also use list(filter(os.path.isfile, bu_dir_list)) but then we need to have a list with PATHS
        # but we need the paths for os.path.getctime anyway
        # filter returns iterator!! that yields items which function is true -> only files
        # iterator -> have to iterate over it or pass it to function that does that -> list() creates a list from it
        # filter prob slower than list comprehension WHEN you call other function (def, lambda, os.path.isfile),
        # WHEREAS you would use a simple if x == "bla" in the list comprehension, here prob same speed

        # if there are more files than number of bu allowed (2 files per bu atm)
        if len(bu_dir_list) > (config.getint("Settings", "max_db_bu", fallback=5) * 2):
            # use creation time (getctime) for sorting, due to how name the files we could also sort alphabetically
            bu_dir_list = sorted(bu_dir_list, key=os.path.getctime)

            logger.info("Too many backups, deleting the oldest one!")
            # remove the oldest two files
            os.remove(bu_dir_list[0])
            os.remove(bu_dir_list[1])
    else:
        # time in sec that is needed to reach next backup
        next_bu = freq_secs - elapsed_time
        logger.info("Der letzte Sicherungszeitpunkt liegt nocht nicht {} Tage zurück! Die nächste Sicherung ist "
                    "in {: .2f} Tagen!".format(config.getint("Settings", "db_bu_freq",
                                                             fallback=5), next_bu / 24 / 60 / 60))


def check_submission_time(submission, lastdltime):
    if submission.created_utc > lastdltime:
        logger.info("Submission is newer than lastdltime")
        return True
    else:
        logger.info("Submission is older than lastdltime")
        return False


if __name__ == "__main__":
    main()
