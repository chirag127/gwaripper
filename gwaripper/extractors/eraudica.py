import re

import bs4

from typing import Optional, Match, cast, Pattern, ClassVar
from urllib.parse import quote as url_quote

from .base import BaseExtractor
from ..info import FileInfo
from ..exceptions import InfoExtractingError


class EraudicaExtractor(BaseExtractor):

    EXTRACTOR_NAME: ClassVar[str] = "Eraudica"
    BASE_URL: ClassVar[str] = "eraudica.com"

    VALID_ERAUDICA_URL_RE: ClassVar[Pattern] = re.compile(
            r"(?:https?://)?(?:www\.)?eraudica\.com/e/eve/"
            r"(?:\d+)/([A-Za-z0-9-]+)", re.IGNORECASE)

    def __init__(self, url: str):
        super().__init__(url)
        # strip("/gwa") doesnt strip the exact string "/gwa" from the end but instead it strips all
        # the chars contained in that string from the end:
        # "eve/Audio-extravaganza/gwa".strip("/gwa") ->  "eve/Audio-extravaganz"
        # use slice instead (replace might remove that string even if its not at the end)
        # remove /gwa from end of link so we can access file download
        if self.url.endswith("/gwa"):
            self.url = self.url[:-4]

    @classmethod
    def is_compatible(cls, url: str) -> bool:
        return bool(cls.VALID_ERAUDICA_URL_RE.match(url))

    def extract(self) -> Optional[FileInfo]:
        html = EraudicaExtractor.get_html(self.url)
        if not html:
            return None

        soup = bs4.BeautifulSoup(html, "html.parser")

        try:
            # selects script tags beneath div with id main and div class post
            # returns list of bs4.element.Tag -> access text with .text
            # get script on eraudica that contains ALL dl information (fn etc. theres also
            # one with just the file url
            scripts = [s.text for s in soup.select("div#main div.post script")
                       if "playerServerURLAuthorityIncludingScheme" in s.text][0]
            # vars that are needed to gen dl link are included in script tag
            # access group of RE (part in '()') with .group(index)
            # Group 0 is always present; it’s the whole RE
            # NOTE: ignore mypy errors with # type: ignore
            # since we except any AttributeError as an indication
            # that sth. went wrong during extraction and that is true here since re.search
            # will only result in an AttributeError if the site changed and our extraction
            # method doesn't work anymore (in another language i'd use ifs instead, but
            # this is more 'pythonic' and efficient since it will raise an Exception only in
            # the very rare case that the site changed, if a substantial proportion of
            # runs it would raise then ifs are actually alot faster)
            # cast is better form since it only applies to one specific expression
            fname = cast(Match, re.search("var filename = \"(.+)\"", scripts)).group(1)
            server = cast(Match, re.search("var playerServerURLAuthorityIncludingScheme = "
                                           "\"(.+)\"", scripts)).group(1)
            dl_token = cast(Match, re.search("var downloadToken = \"(.+)\"",
                                             scripts)).group(1)
            # convert unicode escape sequences (\\u0027) that might be in the filename to str
            # fname.encode("utf-8").decode("unicode-escape")
            # bytes(fname, 'ascii').decode('unicode-escape')
            fname = fname.encode("utf-8").decode("unicode-escape")
            # convert fname to make it url safe with urllib.quote (quote_plus replaces spaces
            # with plus signs)
            fname = url_quote(fname)

            direct_url = "{}/fd/{}/{}".format(server, dl_token, fname)
            title = cast(Match, re.search("var title = \"(.+)\";", scripts)).group(1)
            # mixes escaped (\\u..) with unescaped unicode
            # encode to bytes escaping unicode code points
            # already escaped sequences get esacped as \\\\u.. -> remove extra \\
            # and unescape back to unicode
            title = title.encode("unicode-escape").replace(
                        b'\\\\u', b'\\u').decode('unicode-escape')
            ext = fname.rsplit(".", 1)[1]

            # :not(.love-and-favorite-row) doesn't work with bs4
            descr = "\n\n".join([p.get_text() for p in soup.select('div.description > p')][1:])

            # hardcoded author name
            return FileInfo(self.__class__, True, ext, self.url,
                            direct_url, None, title, descr, "Eves-garden")
        except (IndexError, AttributeError):
            raise InfoExtractingError(
                    "Error occured while extracting eraudica info - site structure "
                    "probably changed! See if there are updates available!",
                    self.url, html)
