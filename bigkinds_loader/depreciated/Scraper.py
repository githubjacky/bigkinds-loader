from datetime import datetime, timedelta
from pathlib import Path


class Scraper():
    def __init__(self,
                 begin: str      = '2024-01-01',
                 end: str        = '2024-01-31',
                 interval: int   = 10,
                 timeout: int    = 30000,
                 output_dir: str = 'data'):

        self.begin_date = datetime.strptime(begin, '%Y-%m-%d')
        self.end_date   = datetime.strptime(end, '%Y-%m-%d')
        self.interval   = interval
        self.timeout    = timeout
        self.output_dir = Path(output_dir)


    def add_zero(self, x: int) -> str:
        str_x = str(x)
        return "0"+str_x if len(str_x) == 1 else str_x


    def datetime_to_str(self, d: datetime) -> str:
        return f"{d.year}-{self.add_zero(d.month)}-{self.add_zero(d.day)}"


    def construct_period(self) -> None:
        days = (self.end_date - self.begin_date).days + 1
        t = (
            days // self.interval
            if self.begin_date.month == 2
            else
            days // self.interval - 1
        )

        period_dict = {'begin': [], 'end': []}
        begin = self.begin_date
        end = self.begin_date + timedelta(days=self.interval-1)

        for _ in range(t):
            period_dict['begin'].append(self.datetime_to_str(begin))
            period_dict['end'].append(self.datetime_to_str(end))

            begin += timedelta(days=self.interval)
            end += timedelta(days=self.interval)

        period_dict['begin'].append(self.datetime_to_str(begin))
        period_dict['end'].append(self.datetime_to_str(self.end_date))

        self.period = period_dict
        self.num_period = len(period_dict['begin'])
