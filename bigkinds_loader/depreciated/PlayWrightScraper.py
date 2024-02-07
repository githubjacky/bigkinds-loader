from loguru import logger
import logging
from pathlib import Path
from typing import List
from playwright.sync_api import sync_playwright, TimeoutError
import pandas as pd
from shutil import rmtree
import sys
from tqdm import trange

from .Scraper import Scraper


class PlayWrightScraper(Scraper):
    def __init__(self,
                 begin: str      = '2024-01-01',
                 end: str        = '2024-01-31',
                 interval: int   = 10,
                 timeout: int    = 30000,
                 output_dir: str = 'data',
                 headless        = True):

        super().__init__(begin, end, interval, timeout, output_dir)
        self.begin    = begin
        self.end      = end
        self.headless = headless


    def create_page(self) -> None:
        p = sync_playwright().start()
        browser = p.chromium.launch(headless=self.headless, slow_mo=100)
        page = browser.new_page()
        self.page = page

        self.page.goto(
            'https://www.bigkinds.or.kr/v2/news/index.do',
            timeout=self.timeout
        )


    def login(self, email: str, password: str):
        # note: do not use: button[type=button]
        self.page.click('div.login-area')
        self.page.fill('input#login-user-id', email)
        self.page.fill('input#login-user-password', password)
        self.page.click('button[type=submit]')


    def __input_period(self, begin, end):
        self.page.fill('input#search-begin-date', begin)
        self.page.fill('input#search-end-date', end)
        self.page.click('button.news-report-search-btn')


    def __trace(self, temp_folder, press) -> None:
        self.page.click('a:has-text("기간")')
        for t in trange(len(self.period['begin'])):
            # select the period
            begin = self.period['begin'][t]
            end = self.period['end'][t]
            self.__input_period(begin, end)

            # check if the number of articles exceed 20,000
            num_article = (
                self.page
                .locator('span.total-news-cnt')
                .first
                .inner_text()
            )
            if int(num_article.replace(',', '')) > 20000:
                logger.warning("the number of articles exceed the limit")

            # download
            self.page.click('button#collapse-step-3')
            res_path = temp_folder / f'{begin}_{end}_{press}.xlsx'
            with self.page.expect_download(timeout=self.timeout) as d:
                self.page.click(
                    '#analytics-data-download > div.btm-btn-wrp > button'
                )
            download = d.value
            download.save_as(res_path)

            # rerun the whole process
            self.page.click('button#collapse-step-1')


    def download_by_press(self, press: str, prev_press=None) -> None:
        logger.info("start downloading")
        temp_folder = self.output_dir / 'temp'
        if temp_folder.exists():
            rmtree(temp_folder)
        else:
            temp_folder.mkdir(parents=True, exist_ok=True)

        # select the press
        if prev_press is not None:
            self.page.click('a:has-text("언론사")')
            self.page.click(f'label:has-text("{prev_press}")')
        self.page.click(f'label:has-text("{press}")')

        # trace and dowload
        self.__trace(temp_folder, press)


    def download_by_multi_press(self, batch_press: List[str]) -> None:
        logger.info("start downloading")
        temp_folder = self.output_dir / 'temp'
        if temp_folder.exists():
            rmtree(temp_folder)
        else:
            temp_folder.mkdir(parents=True, exist_ok=True)

        # select the press
        for press in batch_press:
            self.page.click(f'label:has-text("{press}")')
            # trace and dowload
        self.__trace(temp_folder, '_'.join(batch_press))


    def merge(self, label) -> None:
        logger.info("start merging files")
        temp_dir = self.output_dir / 'temp'
        filenames = temp_dir.glob("*.xlsx")

        df_list = [
            pd.read_excel(file, sheet_name="sheet")
            for file in filenames
        ]
        df = pd.concat(df_list, ignore_index=True).sort_values(by='일자')

        res_file = '_'.join((
            label,
            self.datetime_to_str(self.begin_date),
            self.datetime_to_str(self.end_date),
        )) + '.csv'

        df.to_csv(self.output_dir / res_file, index=False)

        rmtree(temp_dir, ignore_errors=True)
        logger.info("finish the process")


    def __fetch_data_id(self,
                        press: str | List[str],
                        input_begin_date: str,
                        input_end_date: str
                        ) -> List[str]:
        self.create_page()
        match press:
            case str():
                self.page.click(
                    f'label:has-text("{press}")',
                    timeout=self.timeout
                )
            case [*_]:
                for p in press:
                    self.page.click(
                        f'label:has-text("{p}")',
                        timeout=self.timeout
                    )

        self.page.click('a:has-text("기간")')
        if self.begin is None and self.end is None:
            self.page.click('label:has-text("전체")')
            self.page.click('button.news-report-search-btn')
        else:
            self.__input_period(
                input_begin_date,
                input_end_date
            )

        try:
            num_page = (
                self.page.locator('div.lastNum')
                .first
                .get_attribute('data-page')
            )
        except TimeoutError as e:
            logger.warning(
                f"{e}: re-locate the element of number of articles"
            )
            num_page = (
                self.page.locator('div.lastNum')
                .first
                .get_attribute('data-page')
            )

        data_id_list = []
        if num_page is not None:
            for i in trange(int(num_page)):
                self.page                     \
                    .locator('div.news-item') \
                    .first                    \
                    .wait_for(timeout=self.timeout)

                data_id_list += [
                    item.get_attribute('data-id')
                    for item in self.page.locator('div.news-item').all()
                ]
                self.page.fill('input#paging_news_result', str(i+2))
                self.page.keyboard.press('Enter', delay=5000)
        else:
            logger.error("fail to identify the number of page")
            sys.exit

        return data_id_list


    def collect_data_id(self,
                        press: str | List[str],
                        method: str = 'httpx'
                        ) -> List[str] | List[List[str]]:
        logging.getLogger("httpx").setLevel(logging.WARNING)

        log_dir = Path('log')
        log_dir.mkdir(parents=True, exist_ok=True)

        log_file = log_dir / 'collect_data_id.log'
        log_file.unlink(missing_ok=True)

        logger.add(log_file, level='INFO')

        target_dir = (
            Path('env')
            /
            Path(
                (
                    press
                    if isinstance(press, str)
                    else
                    '_'.join(press)
                )
                +
                '_data_id'
            )
            /
            str(self.begin_date.year)
        )
        target_dir.mkdir(parents=True, exist_ok=True)

        input_begin_date = self.datetime_to_str(self.begin_date)
        input_end_date = self.datetime_to_str(self.end_date)

        target_file = (
            target_dir
            /
            (input_begin_date + '_' + input_end_date + '.txt')
        )

        logger.info("start collecting data id through playwright")
        if not target_file.is_file():
            data_id_list = self.__fetch_data_id(
                press,
                input_begin_date,
                input_end_date
            )
            with open(target_file, 'w') as f:
                f.writelines([id + '\n' for id in data_id_list])
        else:
            logger.info("fetch data id from file")
            with open(target_file, 'r')as f:
                data_id_list = f.readlines()

        return data_id_list
