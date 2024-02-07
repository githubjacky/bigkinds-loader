import os, sys
sys.path.append(os.path.abspath(os.getcwd()))

import hydra
from omegaconf import DictConfig

from bigkinds_loader import Scraper


@hydra.main(config_path="../config", config_name="main", version_base=None)
def main(cfg: DictConfig):
    agent = Scraper()
    agent.get_news_batch(cfg.press, cfg.timeout, cfg.begin, cfg.end)


if __name__ == "__main__":
    main()
