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
make doc

# development IDE - Jupyter Lab
make jupyter
```


## Usage
1. download the [MongoDB](https://www.mongodb.com/try/download/community) and start the server
2. create a .env file and assign your own environment variables
```sh
# docker user id
UID=1106
# docker group id
GID=1106
# docker user name
DOCKER_USER="1106"
# docker working directory
PROJ="bigkinds-loader"
# mongodb user
MONGODB_USER="1106"
# mongodb password
MONGODB_PASS="1106"
# mongodb connection string
CONN_STR="mongodb://$MONGODB_USER:$MONGODB_PASS@mongodb"
```
- modify the configuration file - `config/main.yaml`
- run the program
```sh
make up
```
- stop the container
```sh
make down
```
