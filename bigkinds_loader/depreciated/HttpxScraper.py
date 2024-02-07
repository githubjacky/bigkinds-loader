import asyncio
from aiolimiter import AsyncLimiter
from datetime import datetime, timedelta
from functools import partial
import httpx
import itertools
import json
from loguru import logger
from multiprocessing import Pool, RLock
import logging
import nest_asyncio
import orjson
from omegaconf import ListConfig
import sys
from pathlib import Path
from typing import List, Optional, Dict
from tqdm import tqdm
from tqdm.asyncio import tqdm_asyncio

from Scraper import Scraper


async def fetch_data_id(press_code: List[str],
                        start_no: str,
                        client: httpx.AsyncClient,
                        begin_date: str,
                        end_date: str,
                        limiter: AsyncLimiter
                        ) -> List[str]:

    json = {
        "searchSortType": "date",
        "sortMethod": "date",
        "startDate": begin_date,
        "endDate": end_date,
        "providerCodes": press_code,
        "startNo": start_no,
        "resultNumber": "100",
        "isTmUsable": False,
        "isNotTmUsable": False
    }

    async with limiter:
        try:
            r = await client.post(
                'https://www.bigkinds.or.kr/api/news/search.do',
                json=json
            )
        except (
            httpx.ConnectError,
            httpx.RemoteProtocolError,
            httpx.ReadTimeout,
            httpx.ConnectTimeout
        ) as e:

            logger.info(f"{begin_date}/{end_date}: {e}, re-send the request")
            json["resultNumber"] = "10"

            while True:
                try:
                    r = await client.post(
                        'https://www.bigkinds.or.kr/api/news/search.do',
                        json=json
                    )
                    break

                except (
                    httpx.ConnectError,
                    httpx.RemoteProtocolError,
                    httpx.ReadTimeout,
                    httpx.ConnectTimeout
                ) as e:
                    logger.info(
                        f"{begin_date}/{end_date}: {e}, re-send the request"
                    )

        if r.status_code == httpx.codes.OK:
            return [
                item['NEWS_ID']
                for item in r.json()['resultList']
            ]
        else:
            logger.info(f"invalid request: {r.status_code}")
            return [""]


async def async_fetch_data_id(press_code: List[str],
                              headers: Dict[str, str],
                              timeout: int,
                              async_max_rate: int,
                              async_time_period: int,
                              begin_date: str,
                              end_date: str,
                              proxy: str,
                              process_id: int
                              ):
    r = httpx.post(
        'https://www.bigkinds.or.kr/api/news/search.do',
        headers=headers,
        proxies=proxy,
        json={
            "searchSortType": "date",
            "sortMethod": "date",
            "startDate": begin_date,
            "endDate": end_date,
            "providerCodes": press_code,
            "startNo": "1",
            "resultNumber": "100",
            "isTmUsable": False,
            "isNotTmUsable": False
        },
        timeout=timeout
    )

    if r.status_code == httpx.codes.OK:
        num_page = int(r.json()['totalCount']) // 100 + 1
        rate_limit = AsyncLimiter(
            async_max_rate,
            async_time_period
        )

        async with httpx.AsyncClient(
            headers=headers,
            proxies=proxy,
            timeout=timeout
        ) as client:
            tasks = [
                asyncio.create_task(
                    fetch_data_id(
                        press_code,
                        str(i+1),
                        client,
                        begin_date,
                        end_date,
                        rate_limit
                    )
                )
                for i in range(num_page)
            ]

            return await tqdm_asyncio.gather(
                *tasks,
                desc=f"fetch data id from {proxy}:{begin_date}/{end_date}",
                position=process_id
            )
    else:
        logger.error("fail to identify the number of page")
        sys.exit


def mp_fetch_data_id(press_code: List[str],
                     target_dir: Path,
                     log_file: Path,
                     headers: Dict[str, str],
                     timeout: int,
                     async_max_rate: int,
                     async_time_period: int,
                     begin_date: str,
                     end_date: str,
                     proxy: str,
                     process_id: int,
                     ) -> List[str]:

    logger.remove()
    logger.add(log_file, level='INFO', enqueue=True)

    target_file = (
        target_dir
        /
        (begin_date + '_' + end_date + '.txt')
    )

    if not target_file.is_file():
        nest_asyncio.apply()
        data_id_list_item = list(itertools.chain.from_iterable([
            item
            for item in asyncio.run(
                async_fetch_data_id(
                    press_code,
                    headers,
                    timeout,
                    async_max_rate,
                    async_time_period,
                    begin_date,
                    end_date,
                    proxy,
                    process_id
                )
            )
            if item != ""
        ]))

        with open(target_file, 'w') as f:
            f.writelines(
                [id + '\n' for id in data_id_list_item]
            )
    else:
        logger.info(
            f"fetch data id from file: {begin_date}/{end_date}"
        )

        with open(target_file, 'r')as f:
            data_id_list_item = f.readlines()

    return data_id_list_item


def query_string(data_id: str) -> Dict[str, str]:
    return {
        "docId": f"{data_id}",
        "returnCnt": "1",
        "sectionDiv": "1000"
    }


def parse_sim(sim: str) -> Dict[str, float]:
    res = {}
    for word_score in sim.split(' OR '):
        word, score = word_score.split('^')
        res[word] = float(score)

    return res


async def fetch_news(data_id: str,
                     client,
                     limiter: AsyncLimiter,
                     begin_date: str,
                     end_date: str
                     ) -> Dict[str, str]:
    request_url = "https://www.bigkinds.or.kr/news/detailView.do"

    async with limiter:
        try:
            r = await client.get(
                request_url,
                params=query_string(data_id),
            )
        except Exception as e:
            logger.info(f"{begin_date}/{end_date}: {e}, re-send the request")
            while True:
                try:
                    r = await client.get(
                        request_url,
                        params=query_string(data_id),
                    )
                    break
                except Exception as e:
                    logger.info(
                        f"{begin_date}/{end_date}: {e}, re-send the request")

        if r.status_code == httpx.codes.OK:
            detail = r.json()['detail']
            return {
                'date': detail['DATE'],
                'title': detail['TITLE'],
                'content': detail['CONTENT']
                # 'location': response['TMS_NE_LOCATION'].split('\n'),
                # 'category': response['CATEGORY_MAIN'].split('>'),
                # 'relevant': self.__parse_sim(response['TMS_SIMILARITY'])
            }
        else:
            return {"": ""}


async def async_fetch_news(data_id_list: List[str],
                           headers: Dict[str, str],
                           timeout: int,
                           async_max_rate: int,
                           async_time_period: int,
                           begin_date: str,
                           end_date: str,
                           proxy: str,
                           process_id: int
                           ):
    rate_limit = AsyncLimiter(
        async_max_rate,
        async_time_period
    )

    async with httpx.AsyncClient(
        headers=headers,
        proxies=proxy,
        timeout=timeout
    ) as client:
        tasks = [
            asyncio.create_task(
                fetch_news(
                    id,
                    client,
                    rate_limit,
                    begin_date,
                    end_date
                )
            )
            for id in data_id_list
        ]

        return await tqdm_asyncio.gather(
            *tasks,
            desc=f"fetch news from {proxy}: {begin_date}/{end_date}",
            position=process_id
        )


def mp_fetch_news(press: str,
                  target_dir: Path,
                  log_file: Path,
                  headers: Dict[str, str],
                  timeout: int,
                  async_max_rate: int,
                  async_time_period: int,
                  data_id_list: List[str],
                  begin_date: str,
                  end_date: str,
                  proxy: str,
                  process_id: int
                  ) -> None:
    logger.remove()
    logger.add(log_file, level='INFO', enqueue=True)

    target_file = (
        target_dir
        /
        (press + '_' + begin_date + '_' + end_date + '.jsonl')
    )
    if not target_file.exists():
        nest_asyncio.apply()
        news_list = [
            item
            for item in asyncio.run(
                async_fetch_news(
                    data_id_list,
                    headers,
                    timeout,
                    async_max_rate,
                    async_time_period,
                    begin_date,
                    end_date,
                    proxy,
                    process_id
                )
            )
            if item != {"": ""}
        ]
        news_list.reverse()

        with open(target_file, 'wb') as f:
            for news in news_list:
                f.write(orjson.dumps(news, option=orjson.OPT_APPEND_NEWLINE))
    else:
        logger.info(f"fetch news from file: {begin_date}/{end_date}")


class HttpxScraper(Scraper):
    def __init__(self,
                 begin: Optional[str] = None,
                 end: Optional[str] = None,
                 interval: Optional[int] = None,
                 timeout: Optional[int] = None,
                 proxy: Optional[str | ListConfig] = None,
                 async_max_rate: Optional[int] = None,
                 async_time_period: Optional[int] = None,
                 output_dir: Optional[Path] = None
                 ) -> None:
        super().__init__(begin, end, interval, timeout, output_dir)

        self.proxy = (
            proxy if isinstance(proxy, str) else list(proxy)
            if proxy is not None
            else
            'http://143.244.60.116:8443'
        )

        self.async_max_rate = (
            async_max_rate
            if async_max_rate is not None
            else
            100
        )
        self.async_time_period = (
            async_time_period
            if async_time_period is not None
            else
            3
        )

        self.headers = {
            "Referer": "https://www.bigkinds.or.kr/v2/news/index.do",
            "User-Agent": " ".join((
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
                "AppleWebKit/537.36 (KHTML, like Gecko)"
                "Chrome/115.0.0.0 Safari/537.36",
            ))
        }

    @ property
    def press2code(self) -> Dict[str, str]:
        file = Path('env/press_code.json')
        if file.exists():
            return {
                dict['press']: dict['code']
                for dict in json.loads(file.read_text())
            }
        else:
            logger.error("fail to find reference mapping press to code")
            sys.exit()

    def __valid_proxy(self, proxy: str) -> bool:
        invalid_file = Path('env/invalid_proxy.txt')
        if invalid_file.exists():
            with open(invalid_file, 'r') as f:
                invalid_proxy = f.readlines()
            if proxy in invalid_proxy:
                logger.info(f"invalid: {proxy}")
                return False
            else:
                return True
        else:
            logger.info("fail to find reference identifing invalid proxy")
            return True

    def __test_proxy(self, proxy: str) -> str:
        try:
            r = httpx.post(
                'https://www.bigkinds.or.kr/api/news/search.do',
                headers=self.headers,
                proxies=proxy,
                json={
                    "searchSortType": "date",
                    "sortMethod": "date",
                    "startDate": "2023-08-01",
                    "endDate": "2023-08-01",
                    "providerCodes": ["02100601"],
                    "startNo": "1",
                    "resultNumber": "10",
                    "isTmUsable": False,
                    "isNotTmUsable": False
                },
                timeout=self.timeout
            )
            if r.status_code == httpx.codes.OK:
                logger.info(f"status OK: {proxy}")
                return proxy
            else:
                logger.info(f"connection error({r.status_code}): {proxy}")

                if f"{proxy}\n" not in \
                        open('env/invalid_proxy.txt', 'r').readlines():

                    with open('env/invalid_proxy.txt', 'a') as f:
                        f.write(f"{proxy}\n")
                else:
                    logger.info("invalid proxy")

                return ""
        except Exception as e:
            logger.info(f"connection error({e}): {proxy}")

            if f"{proxy}\n" not in \
                    open('env/invalid_proxy.txt', 'r').readlines():

                with open('env/invalid_proxy.txt', 'a') as f:
                    f.write(f"{proxy}\n")
            else:
                logger.info("invalid proxy")

            return ""

    def check_proxy(self) -> None:
        logger.info("check connection of proxy")
        proxy = self.proxy
        if isinstance(proxy, str):
            if not self.__valid_proxy(proxy):
                sys.exit()
            else:
                check = self.__test_proxy(proxy)
                if check != "":
                    self.checked_proxy = proxy
                    self.num_mp_process = 1
                else:
                    sys.exit()
        else:
            if len(proxy) == 1:
                proxy_ = str(proxy[0])
                if not self.__valid_proxy(proxy_):
                    sys.exit()
                else:
                    check = self.__test_proxy(proxy_)
                    if check != "":
                        self.checked_proxy = proxy_
                        self.num_mp_process = 1
                    else:
                        sys.exit()
            else:
                checked_proxy = []
                for i in proxy:
                    test = self.__test_proxy(str(i))
                    if test != "":
                        checked_proxy.append(test)

                self.num_mp_process = len(checked_proxy)
                self.checked_proxy = checked_proxy

    def schedule_proxy(self) -> None:
        self.construct_period()
        logger.info("schedule valid proxy")
        if isinstance(self.checked_proxy, str):
            scheduled_proxy = [self.checked_proxy]*self.num_period
        else:
            scheduled_proxy = [
                self.checked_proxy[(i+1) % self.num_mp_process - 1]
                for i in range(self.num_period)
            ]
        self.scheduled_proxy = scheduled_proxy

    def collect_data_id(self,
                        press: str | List[str],
                        ) -> List[List[str]]:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        self.check_proxy()
        self.schedule_proxy()

        log_dir = Path('log')
        log_dir.mkdir(parents=True, exist_ok=True)

        log_file = log_dir / 'collect_data_id.log'
        log_file.unlink(missing_ok=True)

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

        press2code = self.press2code
        press_code = (
            [press2code[press]]
            if isinstance(press, str)
            else
            [press2code[item] for item in press]
        )
        logger.info(f"press code: {press_code}")

        func = partial(
            mp_fetch_data_id,
            press_code,
            target_dir,
            log_file,
            self.headers,
            self.timeout,
            self.async_max_rate,
            self.async_time_period,
        )
        argument_list = [
            (
                self.period['begin'][i],
                self.period['end'][i],
                self.scheduled_proxy[i],
                i
            )
            for i in range(self.num_period)
        ]

        logger.info("collect data id through httpx")

        with Pool(
            processes=self.num_mp_process,
            initializer=tqdm.set_lock,
            initargs=(RLock(),)
        ) as p:
            data_id_list = p.starmap(func, argument_list)

        logger.info("finish fetch the data id")

        return data_id_list

    def collect_news(self,
                     press: str,
                     data_id_list_cluster: List[List[str]]
                     ) -> None:
        self.id_check = {
            data_id: 0
            for data_id in itertools.chain.from_iterable(data_id_list_cluster)
        }

        logging.getLogger("httpx").setLevel(logging.WARNING)

        log_file = Path('log') / 'collect_news.log'
        log_file.unlink(missing_ok=True)

        output_dir = (
            self.output_dir
            /
            f'{press}/{str(self.begin_date.year)}'
        )
        target_dir = (
            output_dir
            /
            f'{self.add_zero(self.begin_date.month)}'
        )
        target_dir.mkdir(parents=True, exist_ok=True)

        func = partial(
            mp_fetch_news,
            press,
            target_dir,
            log_file,
            self.headers,
            self.timeout,
            self.async_max_rate,
            self.async_time_period
        )
        argument_list = [
            (
                data_id_list_cluster[i],
                self.period['begin'][i],
                self.period['end'][i],
                self.scheduled_proxy[i],
                i
            )
            for i in range(self.num_period)
        ]

        logger.info("collect news through httpx")

        with Pool(
            processes=self.num_mp_process,
            initializer=tqdm.set_lock,
            initargs=(RLock(),)
        ) as p:
            p.starmap(func, argument_list)

        logger.info("finish fetch the data id")

        logger.info(f"merge the file under: {target_dir}")

        output_file = (
            output_dir
            /
            "_".join((
                press,
                str(self.begin_date.year),
                f'{self.add_zero(self.begin_date.month)}.jsonl'
            ))
        )
        with open(output_file, 'wb') as f1:
            attend_list = []
            for file in sorted(list(target_dir.glob('*'))):
                attend_list += [
                    orjson.loads(line)
                    for line in open(file, 'r')
                    if line != '\n'
                ]

            for item in attend_list:
                f1.write(orjson.dumps(item, option=orjson.OPT_APPEND_NEWLINE))
