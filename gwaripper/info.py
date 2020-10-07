import os
import logging
import re

from typing import Optional, Union, List
from collections import deque

logger = logging.getLogger(__name__)

DELETED_USR_FOLDER = "deleted_users"
# own limit; nothing to do with OS dependent MAX_PATH
FILENAME_MAX_LEN = 185


def sanitize_filename(subpath_len: int, filename: str):
    # [^\w\-_\.,\[\] ] -> match not(^) any of \w \- _  and whitepsace etc.,
    # replace any that isnt in the  [] with _
    chars_remaining = FILENAME_MAX_LEN - subpath_len
    assert chars_remaining >= 30
    return re.sub(r"[^\w\-_.,\[\] ]", "_", filename[:chars_remaining])


def children_iter_dfs(start_list: List[Union['FileInfo', 'FileCollection']],
                      file_info_only: bool = False,
                      relative_enum: bool = False) -> (int, Union['FileInfo', 'FileCollection']):
    """
    Iterator over a list containing FileInfo or FileCollection objects and their
    childrne using DFS
    (Iterates over all the files until it finds a collection then it iterates over
     those files first and so on)
    Yields 2-tuple of 0-based index and Union[FileInfo, FileCollection]
    :param relative_enum: Yield relative index when iterating: e.g. Fi0 Fc1 (Fi0 Fi1 Fi2) Fi2
                          otherwise global Fi0 Fc1 (Fi2 Fi3 Fi4) Fi5
    :param file_info_only: Only iterator over FileInfo instances
    """
    # NOTE: dfs to iter all of the downloads since FileCollections can be recursive
    # only one level though since only RedditInfo is allowed as parent for FileCollection
    stack = []
    cur_collection = start_list
    i = 0
    enumerator = 0
    while True:
        if i >= len(cur_collection):
            if not stack:
                break
            else:
                i, cur_collection = stack.pop()
                continue
        cur = cur_collection[i]
        try:
            assert cur.children
            stack.append((i + 1, cur_collection))
            if not file_info_only:
                yield i if relative_enum else enumerator, cur
                enumerator += 1
            cur_collection = cur.children
            i = 0
        except AttributeError:
            # not a FileCollection
            yield i if relative_enum else enumerator, cur
            i += 1
            enumerator += 1


def children_iter_bfs(start_list: List[Union['FileInfo', 'FileCollection']],
                      file_info_only: bool = False,
                      relative_enum: bool = False) -> (int, Union['FileInfo', 'FileCollection']):
    """
    Iterator over a list containing FileInfo or FileCollection objects and their
    childrne using DFS
    (Iterates over all the files until it finds a collection then it iterates over
     those files first and so on)
    Yields 2-tuple of 0-based index and Union[FileInfo, FileCollection]
    :param relative_enum: Yield relative index when iterating: e.g. Fi0 Fc1 (Fi0 Fi1 Fi2) Fi2
                          otherwise global Fi0 Fc1 (Fi2 Fi3 Fi4) Fi5
    :param file_info_only: Only iterator over FileInfo instances
    """
    # NOTE: bfs to iter all of the downloads since FileCollections can be recursive
    # only one level though since only RedditInfo is allowed as parent for FileCollection

    # queue all the list items here and then queue all children if we
    # come across a FileCollection
    q = deque([(i, item) for i, item in enumerate(start_list)])
    enumerator = 0
    while q:
        i, cur = q.popleft()
        # Easier to ask for forgiveness than permission
        # try/except most pythonic, hasattr also okay since goes well with duck typing
        # using isinstance and type not so good
        try:
            assert cur.children
            q.extend([(i, item) for i, item in enumerate(cur.children)])
            if not file_info_only:
                yield i if relative_enum else enumerator, cur
                enumerator += 1
        except AttributeError:
            # not a FileCollection
            yield i if relative_enum else enumerator, cur
            enumerator += 1


# from .extractors.base import BaseExtractor
# does not work due to circular dependency
# to use a forward reference (PEP484):
# When a type hint contains names that have not been defined yet, that
# definition may be expressed as a string literal, to be resolved later
# <py3.7 you have to use a string explicitly
# p3.7+ you can do: from __future__ import annotations
# -> and all the type hints will become strings implicitly
class FileInfo:
    def __init__(self, extractor: 'BaseExtractor', is_audio: bool, ext: str,
                 page_url: str, direct_url: str, _id: Optional[str],
                 title: Optional[str], descr: Optional[str], author: Optional[str],
                 parent: Optional['FileCollection'] = None,
                 reddit_info: Optional['RedditInfo'] = None):
        self.extractor = extractor
        self.is_audio = is_audio
        self.ext = ext
        self.page_url = page_url
        self.direct_url = direct_url
        self.id = _id
        self.title = title
        self.descr = descr
        self.author = author
        self.parent = parent
        self.reddit_info = reddit_info

    def __str__(self):
        return f"FileInfo<{self.page_url}>"

    def generate_filename(self, file_index: int = 0) -> (str, str, str):
        """
        Generates filename to save file locally by replacing chars in the title that are not:
        \\w(regex) - , . _ [ ] or a whitespace(" ")
        with an underscore and limiting its length. If file exists it adds a number padded
        to a width of 2 starting at one till there is no file with that name

        :param file_index: When part of a FileCollection and the files should be numbered
                           0 means no numbering
        :return: Tuple of subpath(for non-audio file collections >=3 files), filename and
                 extension
        """

        title = []
        # NOTE: subpath inside gwaripper root -> usr name folder
        subpaths = []
        if self.parent:
            # reddit_title can only be a RedditInfo.title
            # but parent_title can also be a RedditInfo.title
            parent_title = self.parent.title if self.parent.title else self.parent.id
            # TODO IMPORTANT: reddit_info None for erdaudica from reddit post
            if self.reddit_info is not None:
                # reddit_info.subpath -> save everything in that folder
                # even if further FileCollections would have a subpath
                if self.reddit_info.subpath:
                    subpaths.append(self.reddit_info.subpath)
                    if parent_title:
                        title.append(parent_title[:30])
                else:
                    # other FileCollections can't be >=3 files since then we'd have
                    # a reddit subpath
                    title.append(self.reddit_info.title[:70])
                    if parent_title:
                        title.append(parent_title[:30])
            else:
                # we might have nested FileCollections
                p = self.parent
                while p is not None:
                    # give topmost parent double the chars
                    subpaths.append(p.subpath[:25] if p.parent else p.subpath[:50])
                    p = p.parent
                subpaths.reverse()

                # don't need to include parent_title if we're in our direct
                # parents subpath anyway
                if not self.parent.subpath:
                    title.append(parent_title[:40])

        # file index and file title are always last
        if file_index:
            title.append(f"{file_index:02d}")
        title.append(self.title)
        title = "_".join(title)

        subpath = os.path.join(*subpaths) if subpaths else ""

        filename = sanitize_filename(len(subpath), title)
        return (subpath, filename, self.ext)


class FileCollection:
    def __init__(self, url: str, _id: Optional[str], title: Optional[str],
                 children: Optional[List[Union[FileInfo, 'FileCollection']]] = None):
        self.url = url
        self.id = _id
        self.title = title
        if children is None:
            children = []
        self.author = None
        self.children = children
        self._parent = None

    def __str__(self):
        return f"FileCollection<{self.url}, children: {len(self.children)}>"

    def nr_files(self) -> int:
        return sum(1 for _ in children_iter_dfs(self.children, file_info_only=True))

    @property
    def subpath(self) -> str:
        if self.nr_files() >= 3:
            return f"{self.title if self.title else self.id}"
        else:
            return ""

    @property
    def parent(self):
        return self._parent

    @parent.setter
    def parent(self, parent: 'RedditInfo'):
        self._parent = parent
        # NOTE: set reddit_info on all children when parent gets set since we
        # only accept RedditInfo as parent for FileCollections currently
        for child in self.children:
            child.reddit_info = parent

    def get_preferred_author_name(self) -> str:
        names = [self.author]

        # bfs yields the names in level order level0 then level1 etc.
        for _, child in children_iter_bfs(self.children):
            if child.author:
                names.append(child.author)

        # @Hack
        names.append(DELETED_USR_FOLDER if isinstance(self, RedditInfo) else None)
        names.append("_unknown_user_files")

        # preferred_author_name determines subfolder that the file gets save in
        # return DELETED_USR_FOLDER if neither RedditInfo or parent author nor the files
        # author is known
        # no reddit_info and no known author -> unkown user
        return [n for n in names if n][0]


class RedditInfo(FileCollection):
    def __init__(self, url: str, _id: Optional[str], title: Optional[str],
                 subreddit: str,
                 children: Optional[List[Union[FileInfo, 'FileCollection']]] = None):
        super().__init__(url, _id, title, children=children)
        self.permalink = None
        self.selftext = None
        self.created_utc = None
        self.subreddit = subreddit
        self.r_post_url = None

    def __str__(self):
        return f"RedditInfo<{self.url}, children: {len(self.children)}>"

    @property
    def parent(self):
        # crash here since we never should try to access a RedditInfo parent
        # not true if we just walk up the chain finding the topmost parent etc.
        return None

    @parent.setter
    def parent(self, parent):
        raise Exception("RedditInfo is not allowed to have a parent!")

    def write_selftext_file(self, user_path: str):
        """
        Write selftext to a text file if not None, reddit_info must not be None!!
        Doesnt overwrite already existing selftext file!

        :param user_path: Absolute path to subfolder where files of RedditInfo author are stored
        :return: None
        """
        if not self.selftext:
            return None
        filename = sanitize_filename(len(user_path), self.title)
        # path.join works with joining empty strings
        os.path.join(user_path, self.subpath, filename)
        selftext_fn = f"{filename}.txt"

        if not os.path.isfile(selftext_fn):
            with open(selftext_fn, "w", encoding="UTF-8") as w:
                w.write(f"Title: {self.title}\nPermalink: {self.permalink}\n"
                        f"Selftext:\n\n{self.selftext}")
