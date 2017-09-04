'''
Deploy with command:
fab -f deploy_tools/fab_deploy.py deploy:host=mcscruf61@eds.mindrocket.xyz
'''

from fab_settings import (
    USER_NAME, USER_PW, REPO_URL, PYTHON_VER_NUM, VENV_NAME, APP_NAME, SITE_NAME
)

from fabric.contrib.files import append, exists, sed
from fabric.api import env, local, run
import random


def deploy():
    env.shell = "/bin/bash -l -i -c"
    env.prompts = {
        "Username for 'https://github.com': ": "{}".format(USER_NAME),
        "Password for 'https://{}@github.com': ".format(USER_NAME): "{}".format(USER_PW),
    }

    env.sudo_user = env.user
    env.sudo_password = USER_PW
    env.sudo_prompt = '[sudo] password for {}: '.format(env.user)

    site_folder = '/home/{}/sites/{}'.format(env.user, SITE_NAME)
    source_folder = site_folder + '/source'
    deploy_tools_folder = site_folder + '/deploy_tools'
    virtualenv_folder = '~/.virtualenvs/' + VENV_NAME

    _create_directory_structure_if_necessary(site_folder)
    _get_latest_source(source_folder)
    _update_settings(source_folder, SITE_NAME)
    _update_virtualenv(source_folder, virtualenv_folder)
    _update_static_files(source_folder, virtualenv_folder)
    _update_database(source_folder, virtualenv_folder)
    _restart_gunicorn()


def _create_directory_structure_if_necessary(site_folder):
    for subfolder in ('database', 'static', 'source'):
        run('mkdir -p {}/{}'.format(site_folder, subfolder))


def _get_latest_source(source_folder):
    if not exists(source_folder + '/.git'):
        run('git clone {} {}'.format(REPO_URL, source_folder))
    # run('cd {} && git pull'.format(source_folder,))
    run('cd {} && git fetch'.format(source_folder,))
    current_commit = local("git log -n 1 --format=%H", capture=True)
    run('cd {} && git reset --hard {}'.format(source_folder, current_commit))


def _update_settings(source_folder, site_domain):
    settings_path = source_folder + '/' + APP_NAME + '/settings.py'
    sed(settings_path, "DEBUG = True", "DEBUG = False")
    sed(settings_path,
        'ALLOWED_HOSTS =.+$',
        # 'ALLOWED_HOSTS = ["{}"]'.format("*")
        'ALLOWED_HOSTS = ["{}"]'.format(site_domain)
        )
    secret_key_file = source_folder + '/' + APP_NAME + '/secret_key.py'
    if not exists(secret_key_file):
        chars = 'abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)'
        key = ''.join(random.SystemRandom().choice(chars) for _ in range(50))
        append(secret_key_file, "SECRET_KEY = '{}'".format(key))
    append(settings_path, '\nfrom .secret_key import SECRET_KEY')


def _update_virtualenv(source_folder, virtualenv_folder):
    # virtualenv_folder = '~/.virtualenvs/' + VENV_NAME
    if not exists(virtualenv_folder + '/bin/pip'):
        run('mkvirtualenv -p ~/.pyenv/versions/{}/bin/python {}'.format(PYTHON_VER_NUM, VENV_NAME))
    run('{}/bin/pip install -r {}/requirements.txt'.format(
        virtualenv_folder, source_folder
    ))


def _update_static_files(source_folder, virtualenv_folder):
    virtualenv_folder = '~/.virtualenvs/' + VENV_NAME
    run('cd {} && {}'.format(source_folder, virtualenv_folder) +
        '/bin/python manage.py collectstatic --noinput')


def _update_database(source_folder, virtualenv_folder):
    run('cd {} && {}'.format(source_folder, virtualenv_folder) +
        '/bin/python manage.py migrate --noinput')


def _restart_gunicorn():
    run('sudo systemctl restart gunicorn')
