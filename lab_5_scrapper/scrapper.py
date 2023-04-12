"""
Crawler implementation
"""
import datetime
import concurrent.futures
import json
import re
import shutil
import time
import random
from pathlib import Path
from typing import Pattern, Union
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

from core_utils.article.article import Article
from core_utils.article.io import to_meta, to_raw
from core_utils.config_dto import ConfigDTO
from core_utils.constants import (ASSETS_PATH, CRAWLER_CONFIG_PATH, NUM_ARTICLES_UPPER_LIMIT,
                                  TIMEOUT_LOWER_LIMIT, TIMEOUT_UPPER_LIMIT)


class IncorrectSeedURLError(Exception):
    pass


class NumberOfArticlesOutOfRangeError(Exception):
    pass


class IncorrectNumberOfArticlesError(Exception):
    pass


class IncorrectHeadersError(Exception):
    pass


class IncorrectEncodingError(Exception):
    pass


class IncorrectTimeoutError(Exception):
    pass


class IncorrectVerifyError(Exception):
    pass


class Config:
    """
    Unpacks and validates configurations
    """

    def __init__(self, path_to_config: Path) -> None:
        """
        Initializes an instance of the Config class
        """
        self.path_to_config = path_to_config
        self._validate_config_content()
        self.config_data = self._extract_config_content()
        self._seed_urls = self.config_data.seed_urls
        self._num_articles = self.config_data.total_articles
        self._headers = self.config_data.headers
        self._encoding = self.config_data.encoding
        self._timeout = self.config_data.timeout
        self._should_verify_certificate = self.config_data.should_verify_certificate
        self._headless_mode = self.config_data.headless_mode

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
        config = self._extract_config_content()

        if not isinstance(config.seed_urls, list):
            raise IncorrectSeedURLError("Invalid value for seed_urls in configuration file")

        for seed_url in config.seed_urls:
            if not re.match(r'^https?://.*', seed_url):
                raise IncorrectSeedURLError("Invalid seed URL in configuration file")

        total_articles_to_find_and_parse = config.total_articles
        if not isinstance(total_articles_to_find_and_parse, int) \
                or total_articles_to_find_and_parse < 1:
            raise IncorrectNumberOfArticlesError(
                "Invalid value for total_articles_to_find_and_parse in configuration file")

        if total_articles_to_find_and_parse > NUM_ARTICLES_UPPER_LIMIT:
            raise NumberOfArticlesOutOfRangeError(
                "Invalid value for total_articles_to_find_and_parse in configuration file")

        if not isinstance(config.headers, dict):
            raise IncorrectHeadersError("Invalid value for headers in configuration file")

        if not isinstance(config.encoding, str):
            raise IncorrectEncodingError("Invalid value for encoding in configuration file")

        if not isinstance(config.timeout, int) \
                or config.timeout < TIMEOUT_LOWER_LIMIT or config.timeout > TIMEOUT_UPPER_LIMIT:
            raise IncorrectTimeoutError("Invalid value for timeout in configuration file")

        if not isinstance(config.should_verify_certificate, bool):
            raise IncorrectVerifyError(
                "Invalid value for should_verify_certificate in configuration file")

        if not isinstance(config.headless_mode, bool):
            raise IncorrectVerifyError("Invalid value for headless_mode in configuration file")

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
    response = requests.get(url,
                            headers=config.get_headers(),
                            timeout=config.get_timeout(),
                            verify=config.get_verify_certificate())
    response.encoding = config.get_encoding()
    time.sleep(random.uniform(0.5, 1))
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
        self.seed_urls = config.get_seed_urls()
        self.config = config
        self.urls = []

    def _extract_url(self, article_bs: BeautifulSoup) -> str:
        """
        Finds and retrieves URL from HTML
        """
        href = article_bs.get('href')
        if isinstance(href, str) and \
                href.startswith('https://neva.today/') and href.count('/') == 5:
            return href
        return ''

    def find_articles(self) -> None:
        """
        Finds articles
        """
        for seed_url in self._seed_urls:
            response = make_request(seed_url, self._config)
            article_bs = BeautifulSoup(response.text, 'lxml')
            for elem in article_bs.find_all('a', class_='widget-view-small__head'):
                if len(self.urls) >= self._config.get_num_articles():
                    return
                article_url = self._extract_url(elem)
                if not article_url or article_url in self.urls:
                    continue
                self.urls.append(article_url)


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
        self.article = Article(self.full_url, self.article_id)

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
        title_tag = article_soup.find_all('h1', {'class': 'article__title'})[0]
        if title_tag:
            title = title_tag.get_text(strip=True)
        else:
            title = "NOT FOUND"
        self.article.title = title

        author_tag = article_soup.find_all('p', {'class': 'article__prepared'})
        if author_tag:
            authors = author_tag[0].get_text(strip=True)
        else:
            authors = ["NOT FOUND"]
        self.article.author = authors

        topic_tag = article_soup.find('div', {'class': 'article__category'}).find('a')
        if topic_tag:
            topic = topic_tag.get_text(strip=True)
        else:
            topic = "NOT FOUND"
        self.article.topic = topic

        date_tag = article_soup.find('div', {'class': 'article__date'})
        if date_tag:
            date_str = date_tag.get_text(strip=True)
        else:
            date_str = "NOT FOUND"
        date = self.unify_date_format(date_str)
        if date:
            self.article.date = date
        else:
            self.article.date = datetime.datetime.now()

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
