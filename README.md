# MOSS Automation

## Register for Moss
Follow the instructions in this [link](https://theory.stanford.edu/~aiken/moss/ "link") to create a MOSS account and receive a MOSS USER_ID.

## Create a GitLab token
Follow the instruction in this [link](https://docs.gitlab.com/ee/user/project/settings/project_access_tokens.html "link") to create a GitLab access token.

## .env file
Use env_template to create .env file:
`USER_ID=<moss user id>`
`GITLAB_TOKEN=<gitlab token>`
`GITLAB_URL=<gitlab_url>`

## Install the dependencies
`pip install -r requirements.txt`

## Clone the Repositories
`python run.py -c configs/pa1.yaml -g`

## Run the Moss
`python run.py -c configs/pa1.yaml -m`