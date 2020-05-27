import logging
import sys
import webbrowser
from os import environ
from textwrap import dedent

import git
import requests
from github import Github
from invoke import task

logger = logging.getLogger()


class BuildNotFound(Exception):
    pass


class BuildInProgress(Exception):
    pass


@task()
def digest(c, commit=None):
    commit = commit or get_current_commit(c)
    commitstatus = get_commit_status(c, commit)
    print(get_jenkins_digest(c, commitstatus)[0])


def git_command(c, command):
    result = c.run(f'git {command}', hide='stdout', warn=True)
    if result.exited == 0:
        return result.stdout


def get_current_commit(c):
    return git_command(c, 'rev-parse HEAD')[:-1]


def get_commit_status(c, commit, repo=None):
    if not c.config.github.username or not c.config.github.password:
        print(dedent('''
            Set github.username and github.password.
            Obtain it here https://help.github.com/en/articles/creating-a-personal-access-token-for-the-command-line
            Full "repo" scope is required to access organization private repos.
        '''))
        sys.exit(1)
    if repo is None:
        repo = get_git_repo()
    logger.debug(f"Checking commit status for {repo}:{commit}")
    g = Github(c.config.github.username, c.config.github.password)
    combined = g.get_repo(repo).get_commit(commit).get_combined_status()
    for status in combined.statuses:
        if status.context == 'continuous-integration/jenkins/branch':
            return status
    else:
        raise BuildNotFound()


def get_jenkins_digest(c, commitstatus):
    ci_url = commitstatus.target_url.replace('/display/redirect', '/api/json')
    resp = requests.get(ci_url, auth=(c.jenkins.username, c.jenkins.password))
    resp.raise_for_status()
    for action in resp.json()['actions']:
        if action.get('_class') == 'org.jenkinsci.plugins.custombuildproperties.CustomBuildPropertiesAction':
            return action['properties']['digest'], commitstatus.target_url
    else:
        return None, commitstatus.target_url


def get_git_repo():
    url = git.Repo().remote().url

    ssh_prefix = 'git@github.com:'
    https_prefix = 'https://github.com/'
    if url.startswith(ssh_prefix):
        start = len(ssh_prefix)
    elif url.startswith(https_prefix):
        start = len(https_prefix)
    else:
        start = 0

    if url.endswith('.git'):
        end = -4
    else:
        end = None

    return url[start: end]


@task
def open_ci(c, repo=None):
    commit = get_current_commit(c)
    commitstatus = get_commit_status(c, commit, repo)
    _, ci_url = get_jenkins_digest(c, commitstatus)
    webbrowser.open_new_tab(ci_url)


@task
def deploy(c, namespace=None, digest=None, wait=True):
    commit = get_current_commit(c)
    if not digest:
        if 'DIGEST' in environ:
            digest = environ['DIGEST']
        else:
            commitstatus = get_commit_status(c, commit)
            while True:
                digest, ci_url = get_jenkins_digest(c, commitstatus)
                if digest:
                    break
                elif not wait:
                    raise BuildInProgress(ci_url)
    branch = get_branch(c)
    message = get_message(c)
    author_name = git_command(c, 'log -1 --pretty=format:"%an"')
    author_email = git_command(c, 'log -1 --pretty=format:"%ae"')
    args = dict(
        branch=branch,
        commit=commit,
        owner=get_deployer(c),
        message=message,
    )
    args['image.digest'] = digest
    args['author.name'] = author_name
    args['author.email'] = author_email
    args_str = ''.join(f" --set '{key}={value}'" for key, value in args.items())
    namespace = namespace or c.helm.namespace
    release = c.helm.release + (f'-{namespace}' if namespace else '')
    cmd = f'helm upgrade -i --namespace={namespace} {args_str} {release} ./chart'
    c.run(cmd, echo=True)


def get_deployer(c):
    return environ.get('BUILDKITE_UNBLOCKER') or git_command(c, 'config --get user.name')[:-1]


def get_branch(c):
    if 'BUILDKITE_BRANCH' in environ:
        return environ['BUILDKITE_BRANCH']
    else:
        return git_command(c, 'branch | grep "*"')[2:-1]


def get_message(c):
    if 'BUILDKITE_MESSAGE' in environ:
        message = environ['BUILDKITE_MESSAGE']
    else:
        message = git_command(c, 'log -1 --pretty=%B')[:-2]
    return message.replace(';', '.').replace(',', '.')
