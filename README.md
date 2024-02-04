# bigkinds-loader
*Downloading bigkinds news article.*


## Set up the environment, and Install dependencies
1. Install docker
2. create the docker image:
```bash
make build
```
To clean up the docker image:
```sh
make clean
```


## Container Services
```sh
# unit test
make pytest

# project documentation
make pydoc

# development IDE - Jupyter Lab
make jupyter
```
