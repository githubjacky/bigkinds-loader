from datetime import datetime, timedelta
from typing import Literal
import httpx
import logging
from loguru import logger
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, Page
from pymongo import MongoClient
import sys
from tqdm import trange
from typing import Dict, Generator, Optional


class Scraper:
    url = 'https://www.bigkinds.or.kr/news/detailView.do'
    params = {
        "docId":'',
        "returnCnt":'1',
        "sectionDiv":'1000'
    }
    client = httpx.Client(
        headers = {
            "Referer": 'https://www.bigkinds.or.kr/v2/news/index.do',
            "User-Agent": 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36'
        }
    )


    def __init__(self) -> None:
        pass


    @staticmethod
    def __add_zero(x: int) -> str:
        """Used when transforming datetime to string."""
        str_x = str(x)
        return "0"+str_x if len(str_x) == 1 else str_x


    def __datetime_to_str(self, d: datetime) -> str:
        return f"{d.year}-{self.__add_zero(d.month)}-{self.__add_zero(d.day)}"


    @staticmethod
    def __get_n_pages(page: Page, max_retry: int = 5) -> None | str:
        """Get the number of result pages after inputing the press and period query."""
        retry = 0
        n_pages = None
        while n_pages is None and retry < max_retry:
            try:
                n_pages = (
                    page.locator('div.lastNum')
                    .first
                    .get_attribute('data-page')
                )
            except:
                retry += 1

        return n_pages


    def __news_id_generator(self,
                            press: str                     = '한국경제',
                            headless: Literal[True, False] = False,
                            timeout: int                   = 300000,
                            begin:str                      = '2024-01-01',
                            end: str                       = '2024-01-31'
                           ) -> Generator[str|None, None, None]:

        """Generate the news id to query the whole content of a news article."""
        begin_date = datetime.strptime(begin, '%Y-%m-%d')
        end_date = datetime.strptime(end, '%Y-%m-%d')

        p = sync_playwright().start()
        browser = p.chromium.launch(headless=headless, slow_mo=100)
        page = browser.new_page()

        page.goto(
            'https://www.bigkinds.or.kr/v2/news/index.do',
            wait_until = 'domcontentloaded',
            timeout = timeout
        )
        page.click(f'label:has-text("{press}")')
        page.click('a:has-text("기간")')

        target_date = begin_date
        while target_date <= end_date:
            page.fill('input#search-begin-date', self.__datetime_to_str(target_date))
            page.fill('input#search-end-date', self.__datetime_to_str(target_date))
            page.click('button.news-report-search-btn')

            n_pages = self.__get_n_pages(page)
            if n_pages is not None:
                for i in trange(int(n_pages), desc=f'date: {self.__datetime_to_str(target_date)}'):
                    page                     \
                    .locator('div.news-item') \
                    .first                    \
                    .wait_for(timeout=timeout)

                    for item in page.locator('div.news-item').all():
                        yield item.get_attribute('data-id')

                    page.fill('input#paging_news_result', str(i+2))
                    page.keyboard.press('Enter', delay=20000)
            else:
                logger.info(f'fail to fetch news for {press} at {self.__datetime_to_str(target_date)}')
                sys.exit()

            page.click('button#collapse-step-1')
            target_date += timedelta(1)


    def get_news_instance(self, news_id: str | None) -> Dict[str, str]:
        """Get the content of a news article."""
        if news_id is not None:
            self.params['docId'] = news_id
            r = self.client.get(self.url, params=self.params)
            item = {
                'date': '',
                'title': '',
                'content': '',
                'news_id': news_id,
                'status': str(r.status_code)
            }

            if r.status_code == httpx.codes.OK:
                detail = r.json()['detail']
                item['date'] = detail['DATE']
                item['title'] = detail['TITLE']
                item['content'] = detail['CONTENT']
                logger.info('query success')
            else:
                logger.info('fail to query news')
        else:
            logger.info('invalid news id')
            item = {'status': '-1'}

        return item


    def get_news_batch(self,
                       press: str                     = '한국경제',
                       timeout: int                   = 300000,
                       begin:str                      = '2024-01-01',
                       end: Optional[str]             = None,
                       db_name: Optional[str]         = None,
                       collection_name: Optional[str] = None
                      ) -> None:
        """Main API to query news content based on the press name and the specified period.

        Args:
            `press`:           the press of the newspaper
            `timeout`:         configuration for playwright
            `begin`:           begin date
            `end`:             end date, default to begin(daily frequency)
            `db_name`:         name of the mongodb database, default to `press`
            `collection_name`: name of the collection, default to `begin`

        Returns:
            None, the result will be stored in the mongo database.
        """
        if end is None:
            end = begin
        logging.getLogger("httpx").setLevel(logging.WARNING)

        log_dir = Path(f'log/{press}/{begin.split("-")[0]}')
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.remove()
        logger.add(log_dir / f'{begin}_{end}.log', level='INFO')

        client = MongoClient(os.environ['CONN_STR'])
        db = client[press if db_name is None else db_name]
        collection = db[collection_name if collection_name is not None else begin]

        logger.info('start the query process')
        for news_id in self.__news_id_generator(press, True, timeout, begin, end):
            data  = self.get_news_instance(news_id)
            if data['status'] == '200':
                collection.insert_one(data)

        logger.info('end the query process')
