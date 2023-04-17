"""
Crawler implementation
"""
import datetime
import json
import random
import re
import shutil
import time
from typing import List
from article import Article
from pathlib import Path
from typing import Pattern, Union

import requests
from bs4 import BeautifulSoup

from core_utils.article.article import Article
from core_utils.article.io import to_meta, to_raw
from core_utils.config_dto import ConfigDTO
from core_utils.constants import (ASSETS_PATH, CRAWLER_CONFIG_PATH,
                                  NUM_ARTICLES_UPPER_LIMIT,
                                  TIMEOUT_LOWER_LIMIT, TIMEOUT_UPPER_LIMIT)


class IncorrectSeedURLError(Exception):
    """
    Raised when the seed URL does not match the
    standard pattern or does not correspond to the target website
    """


class NumberOfArticlesOutOfRangeError(Exception):
    """
    Raised when the total number of articles is out of range from 1 to 150
    """


class IncorrectNumberOfArticlesError(Exception):
    """
    Raised when the total number of articles to parse is not an integer
    """


class IncorrectHeadersError(Exception):
    """
    Raised when headers are not in the form of a dictionary
    """


class IncorrectEncodingError(Exception):
    """
    Raised when the encoding is not specified as a string
    """


class IncorrectTimeoutError(Exception):
    """
    Raised when the timeout value is not a positive integer less than 60
    """


class IncorrectVerifyError(Exception):
    """
    Raised when the verify certificate value is not either True or False
    """


class Config:
    """
    Unpacks and validates configurations
    """

    def __init__(self, path_to_config: Path) -> None:
        """
        Initializes an instance of the Config class
        """
        self.path_to_config = path_to_config
        self.config = self._extract_config_content()
        self._validate_config_content()

        self._seed_urls = self.config.seed_urls
        self._num_articles = self.config.total_articles
        self._headers = self.config.headers
        self._encoding = self.config.encoding
        self._timeout = self.config.timeout
        self._should_verify_certificate = self.config.should_verify_certificate
        self._headless_mode = self.config.headless_mode

    def _extract_config_content(self) -> ConfigDTO:
        """
        Returns config values
        """
        with open(self.path_to_config, 'r', encoding='utf-8') as file:
            config = json.load(file)
        return ConfigDTO(**config)

    def _validate_config_content(self) -> None:
        """
        Ensure configuration parameters
        are not corrupt
        """
        if not isinstance(self.config.seed_urls, list):
            raise IncorrectSeedURLError('seed URL is not a list')
        regex = re.compile(r'https?://')
        for url in self.config.seed_urls:
            if not isinstance(url, str):
                raise IncorrectSeedURLError('seed URL is not str')
            if not re.match(regex, url):
                raise IncorrectSeedURLError('seed URL does not match standard pattern')
        if not isinstance(self.config.total_articles, int) or \
                self.config.total_articles <= 0:
            raise IncorrectNumberOfArticlesError('total number of articles to parse is not integer')
        if not 1 <= self.config.total_articles <= NUM_ARTICLES_UPPER_LIMIT:
            raise NumberOfArticlesOutOfRangeError('total number of articles is out of range')
        if not isinstance(self.config.headers, dict):
            raise IncorrectHeadersError('headers are not in a form of dictionary')
        if not isinstance(self.config.encoding, str):
            raise IncorrectEncodingError('encoding must be specified as a string')
        if not isinstance(self.config.timeout, int) or \
                not TIMEOUT_LOWER_LIMIT <= self.config.timeout <= TIMEOUT_UPPER_LIMIT:
            raise IncorrectTimeoutError('timeout value must be a positive integer less than 60')
        if not isinstance(self.config.should_verify_certificate, bool):
            raise IncorrectVerifyError('verify certificate value must either be True or False')
        if not isinstance(self.config.headless_mode, bool):
            raise IncorrectVerifyError('headless mode value must either be True or False')

    def get_seed_urls(self) -> list[str]:
        """
        Retrieve seed urls
        """
        return self._seed_urls

    def get_num_articles(self) -> int:
        """
        Retrieve total number of articles to scrape
        """
        return self._num_articles

    def get_headers(self) -> dict[str, str]:
        """
        Retrieve headers to use during requesting
        """
        return self._headers

    def get_encoding(self) -> str:
        """
        Retrieve encoding to use during parsing
        """
        return self._encoding

    def get_timeout(self) -> int:
        """
        Retrieve number of seconds to wait for response
        """
        return self._timeout

    def get_verify_certificate(self) -> bool:
        """
        Retrieve whether to verify certificate
        """
        return self._should_verify_certificate

    def get_headless_mode(self) -> bool:
        """
        Retrieve whether to use headless mode
        """
        return self._headless_mode


def make_request(url: str, config: Config) -> requests.models.Response:
    """
    Delivers a response from a request
    with given configuration
    """
    time.sleep(random.randint(1, 6))
    response = requests.get(url,
                            headers=config.get_headers(),
                            timeout=config.get_timeout())
    response.encoding = config.get_encoding()
    return response


class Crawler:
    """
    Crawler implementation
    """

    url_pattern: Union[Pattern, str]

    def __init__(self, config: Config) -> None:
        """
        Initializes an instance of the Crawler class
        """
        self.config = config
        self.urls = []
        self._seed_urls = self.config.get_seed_urls()

    def _extract_url(self, article_bs: BeautifulSoup) -> str:
        """
        Finds and retrieves URL from HTML
        """
        url: Union[str, list, None] = article_bs.get('href')
        if isinstance(url, str) and \
                'https://neva.today/' in url:
            return url
        return ''

    def find_articles(self) -> None:
        """
        Finds articles
        """
        num_arts = self.config.get_num_articles()
        for url in self._seed_urls:
            response = make_request(f'{url}?per-page={num_arts}', self.config)
            if response.status_code != 200:
                continue
            main_bs = BeautifulSoup(response.text, 'lxml')
            feed_lines = main_bs.find_all('a', {'class': 'main-block-item'})
            for line in feed_lines:
                if len(self.urls) >= num_arts:
                    break
                if link := self._extract_url(line):
                    self.urls.append(link)

    def get_search_urls(self) -> list:
        """
        Returns seed_urls param
        """
        return self._seed_urls


class HTMLParser:
    """
    ArticleParser implementation
    """

    def __init__(self, full_url: str, article_id: int, config: Config) -> None:
        """
        Initializes an instance of the HTMLParser class
        """
        self.full_url = full_url
        self.article_id = article_id
        self.config = config
        self.article: Article = Article(full_url, article_id)

    def _fill_article_with_text(self, article_soup: BeautifulSoup) -> None:
        """
        Finds text of article
        """
        article = article_soup.find('div', {'itemprop': 'articleBody'})
        article_list = article.find_all('p')
        paragraphs = [par.text for par in article_list]
        self.article.text = '\n'.join(paragraphs)

    def _fill_article_with_meta_information(self, article_soup: BeautifulSoup) -> None:
        """
        Finds meta information of article
        """
        # get id from article tag
        article.id = article_soup['id']

        # get title from h1 tag inside article tag
        title_elem = article_soup.find('h1', {'class': 'page-main__head'})
        article.title = title_elem.text.strip() if title_elem else "NOT FOUND"

        # get author(s) from a tag(s) inside article tag
        author_elem = article_soup.find('a', {'class': 'page-main__publish-author global-link'})
        article.authors = [author_elem.text.strip()] if author_elem else ["NOT FOUND"]

        # get date from a tag inside article tag
        date_elem = article_soup.find('a', {'class': 'page-main__publish-date'})
        date_str = date_elem.text.strip() if date_elem else "NOT FOUND"
        article.date = self.unify_date_format(date_str)

        # get topic from a tag(s) inside article tag
        topic_elem = article_soup.find_all('a', {'class': 'panel-group__title global-link'})[1]
        article.topics = topic_elem.text.strip() if topic_elem else "NOT FOUND"

    def unify_date_format(self, date_str: str) -> datetime.datetime:
        """
        Unifies date format
        """
        months = {
            "января": "january",
            "февраля": "february",
            "марта": "march",
            "апреля": "april",
            "мая": "may",
            "июня": "june",
            "июля": "july",
            "августа": "august",
            "сентября": "september",
            "октября": "october",
            "ноября": "november",
            "декабря": "december"
        }
        for rus_month, en_month in months.items():
            date_str = date_str.replace(rus_month, en_month)
        try:
            result = datetime.datetime.strptime(date_str, '%H:%M, %d %b %Y')
            if result:
                return result
        except ValueError:
            pass
        return datetime.datetime.now()

    def parse(self) -> Union[Article, bool, list]:
        """
        Parses each article
        """
        response = requests.get(self.full_url,
                                headers=self.config.get_headers(),
                                timeout=self.config.get_timeout())
        response.encoding = self.config.get_encoding()
        b_s = BeautifulSoup(response.text, 'lxml')
        self._fill_article_with_text(b_s)
        self._fill_article_with_meta_information(b_s)
        return self.article


def prepare_environment(base_path: Union[Path, str]) -> None:
    """
    Creates ASSETS_PATH folder if no created and removes existing folder
    """
    if base_path.exists():
        shutil.rmtree(base_path)
    base_path.mkdir(parents=True)


def main() -> None:
    """
    Entrypoint for scrapper module
    """
    config = Config(path_to_config=CRAWLER_CONFIG_PATH)
    prepare_environment(ASSETS_PATH)

    crawler = Crawler(config=config)
    crawler.find_articles()

    for i, url in enumerate(crawler.urls, start=1):
        parser = HTMLParser(full_url=url, article_id=i, config=config)
        article = parser.parse()

        if isinstance(article, Article):
            to_raw(article)
            to_meta(article)


if __name__ == "__main__":
    main()
