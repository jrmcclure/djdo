'''
Deploy with command:
fab -f deploy_tools/fab_server.py setup_server:host=mcscruf61@djdo.jrmcclure.com
'''
from fab_settings import (
    USER_NAME, USER_PW, REPO_URL, PYTHON_VER_NUM, VENV_NAME, APP_NAME, SITE_NAME
)

from fabric.contrib.files import append, exists, sed
from fabric.api import env, local, run, sudo
import random
import time
import pipes


def setup_server():
    env.shell = "/bin/bash -l -i -c"
    env.prompts = {
        'Command may disrupt existing ssh connections. Proceed with operation (y|n)? ': 'y\n',
        'Do you want to continue? [Y/n] ': 'y\n',
        'Are you sure you want to continue connecting (yes/no)? ': 'yes\n',
        # "Username for 'https://github.com': ": "{}".format(USER_NAME),
        # "Password for 'https://{}@github.com': ".format(USER_NAME): "{}".format(USER_PW),
        "Password: ": USER_PW,
        "Password (again): ": USER_PW,
    }

    env.sudo_user = env.user
    env.sudo_password = 'tsunami61'
    env.sudo_prompt = '[sudo] password for {}: '.format(env.user)

    home_folder = '/home/{}'.format(env.user)
    virtualenv_folder = '~/.virtualenvs/' + VENV_NAME
    site_folder = '/home/{}/sites/{}'.format(env.user, SITE_NAME)
    source_folder = site_folder + '/source'
    deploy_tools_folder = source_folder + '/deploy_tools'

    _install_updates()
    _install_packages()
    _create_PostsreSQL_database()
    _setup_bash_aliases(home_folder)
    _setup_virtualenv(home_folder, virtualenv_folder)
    _setup_directory_structure(site_folder)
    _get_latest_source(source_folder)
    _update_settings(source_folder)
    _update_virtualenv(source_folder, virtualenv_folder)
    _setup_gunicorn_conf(deploy_tools_folder)
    _setup_nginx_conf(deploy_tools_folder)
    _setup_firewall()
    _setup_letsencrypt(deploy_tools_folder)
    _update_nginx_for_ssl(deploy_tools_folder)
    _setup_cron_to_renew_letsencrypt(deploy_tools_folder)
    _initial_db_migration(source_folder)
    _restart_gunicorn()


def _install_updates():
    # Install required packages
    run('sudo apt-get update')
    run('sudo apt-get dist-upgrade -y')


def _install_packages():
    # Install required packages
    run('sudo apt-get install git python3-pip python3-dev libpq-dev postgresql postgresql-contrib nginx letsencrypt build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev -y')
    run('sudo pip3 install virtualenv virtualenvwrapper')


def postgres(command):
    return run("sudo -u postgres psql -c {}".format(pipes.quote(command)))


def _create_PostsreSQL_database():
    postgres("CREATE DATABASE {}_db;".format(APP_NAME))
    postgres("CREATE USER {} WITH PASSWORD '{}';".format(USER_NAME, USER_PW))
    postgres("ALTER ROLE {} SET client_encoding TO 'utf8';".format(USER_NAME))
    postgres(
        "ALTER ROLE {} SET default_transaction_isolation TO 'read committed';".format(USER_NAME))
    postgres("ALTER ROLE {} SET timezone TO 'UTC';".format(USER_NAME))
    postgres("GRANT ALL PRIVILEGES ON DATABASE {}_db TO {};".format(
        APP_NAME, USER_NAME))


def _setup_bash_aliases(home_folder):
    # Setup virtualenv bash aliases
    append(home_folder + '/.bashrc', '\nexport WORKON_HOME=~/.virtualenvs')
    append(home_folder + '/.bashrc',
           '\nexport VIRTUALENVWRAPPER_PYTHON=/usr/bin/python3')
    append(home_folder + '/.bashrc',
           '\nsource /usr/local/bin/virtualenvwrapper.sh')
    run('source ~/.bashrc')


def _setup_virtualenv(home_folder, virtualenv_folder):
    py_ver = run('python3 --version').strip().split(' ')[1]
    if py_ver == PYTHON_VER_NUM:
        if not exists(virtualenv_folder + '/bin/pip'):
            run('mkvirtualenv {}'.format(VENV_NAME))
    else:
        # Install pyenv
        if not exists(home_folder + '/.pyenv'):
            run('git clone https://github.com/yyuu/pyenv.git ~/.pyenv')
        # Install required version of Python
        if not exists(home_folder + '/.pyenv/versions/{}'.format(PYTHON_VER_NUM)):
            run('sudo ' + home_folder +
                '/.pyenv/bin/pyenv install {}'.format(PYTHON_VER_NUM))
        # Create Virtualenv
        if not exists(virtualenv_folder + '/bin/pip'):
            run('mkvirtualenv -p ~/.pyenv/versions/{}/bin/python {}'.format(PYTHON_VER_NUM, VENV_NAME))


# Setup project directories
def _setup_directory_structure(site_folder):
    for subfolder in ('database', 'static', 'source', 'media'):
        run('mkdir -p {}/{}'.format(site_folder, subfolder))


def _get_latest_source(source_folder):
    if not exists(source_folder + '/.git'):
        run('git clone {} {}'.format(REPO_URL, source_folder))
    run('cd {} && git fetch'.format(source_folder,))
    current_commit = local("git log -n 1 --format=%H", capture=True)
    run('cd {} && git reset --hard {}'.format(source_folder, current_commit))


def _update_settings(source_folder):
    settings_path = source_folder + '/' + APP_NAME + '/settings.py'
    sed(settings_path, "DEBUG = True", "DEBUG = False")
    sed(settings_path,
        'ALLOWED_HOSTS =.+$',
        'ALLOWED_HOSTS = ["{}"]'.format(SITE_NAME)
        )
    secret_key_file = source_folder + '/' + APP_NAME + '/secret_key.py'
    if not exists(secret_key_file):
        chars = 'abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)'
        key = ''.join(random.SystemRandom().choice(chars) for _ in range(50))
        append(secret_key_file, "SECRET_KEY = '{}'".format(key))
        append(settings_path, '\nfrom .secret_key import SECRET_KEY')


def _update_virtualenv(source_folder, virtualenv_folder):
    if not exists(virtualenv_folder + '/bin/pip'):
        run('mkvirtualenv -p ~/.pyenv/versions/{}/bin/python {}'.format(PYTHON_VER_NUM, VENV_NAME))
    run('{}/bin/pip install gunicorn'.format(virtualenv_folder))
    run('{}/bin/pip install -r {}/requirements.txt'.format(
        virtualenv_folder, source_folder
    ))


def _setup_gunicorn_conf(deploy_tools_folder):
    conf_path = deploy_tools_folder + '/gunicorn-systemd.template.conf'
    sed(conf_path, "USER_NAME", USER_NAME)
    sed(conf_path, "SITE_NAME", SITE_NAME)
    sed(conf_path, "VENV_NAME", VENV_NAME)
    sed(conf_path, "APP_NAME", APP_NAME)
    run('cp {} {}/gunicorn.service'.format(conf_path, deploy_tools_folder))
    if not exists('/etc/systemd/system/gunicorn.service'):
        run('sudo mv {}/gunicorn.service /etc/systemd/system/gunicorn.service'.format(deploy_tools_folder))
        run('sudo systemctl start gunicorn')
        run('sudo systemctl enable gunicorn')


def _setup_nginx_conf(deploy_tools_folder):
    conf_path = deploy_tools_folder + '/nginx.template.conf'
    sed(conf_path, "USER_NAME", USER_NAME)
    sed(conf_path, "SITE_NAME", SITE_NAME)
    sed(conf_path, "APP_NAME", APP_NAME)
    run('cp {} {}/{}'.format(conf_path, deploy_tools_folder, SITE_NAME))
    run('sudo cp {}/{} /etc/nginx/sites-available/{}'.format(deploy_tools_folder,
                                                             SITE_NAME, SITE_NAME))
    if not exists('/etc/nginx/sites-enabled/{}'.format(SITE_NAME)):
        run('sudo ln -s /etc/nginx/sites-available/{} /etc/nginx/sites-enabled'.format(SITE_NAME))
    run('sudo systemctl restart nginx')


def _setup_firewall():
    run('sudo ufw allow OpenSSH')
    run('sudo ufw allow "Nginx Full"')
    run('sudo ufw enable')


def _setup_letsencrypt(deploy_tools_folder):
    if not exists('/etc/ssl/certs/dhparam.pem'):
        run('sudo openssl dhparam -out /etc/ssl/certs/dhparam.pem 2048')

    ssl_conf_path = deploy_tools_folder + '/ssl-sitename.conf'
    sed(ssl_conf_path, "SITE_NAME", SITE_NAME)
    run('cp {} {}/ssl-{}.conf'.format(ssl_conf_path, deploy_tools_folder, SITE_NAME))
    # if not exists('/etc/nginx/snippets/ssl-{}.conf'.format(SITE_NAME)):
    run('sudo cp {}/ssl-{}.conf /etc/nginx/snippets/ssl-{}.conf'.format(
        deploy_tools_folder, SITE_NAME, SITE_NAME))

    params_conf_path = deploy_tools_folder + '/ssl-params.conf'
    run('sudo cp {} /etc/nginx/snippets/'.format(params_conf_path))
    run('sudo mkdir -p /var/www/{}/html'.format(SITE_NAME))
    run('sudo letsencrypt certonly -a webroot --keep-until-expiring --agree-tos --email mcclurejr@gmail.com --webroot-path=/var/www/{}/html -d {}'.format(SITE_NAME, SITE_NAME))


def _update_nginx_for_ssl(deploy_tools_folder):
    conf_path = deploy_tools_folder + '/nginx.ssl-template.conf'
    sed(conf_path, "USER_NAME", USER_NAME)
    sed(conf_path, "SITE_NAME", SITE_NAME)
    sed(conf_path, "APP_NAME", APP_NAME)
    run('cp {} {}/{}'.format(conf_path, deploy_tools_folder, SITE_NAME))
    run('sudo cp {}/{} /etc/nginx/sites-available/{}'.format(deploy_tools_folder,
                                                             SITE_NAME, SITE_NAME))
    if not exists('/etc/nginx/sites-enabled/{}'.format(SITE_NAME)):
        run('sudo ln -s /etc/nginx/sites-available/{} /etc/nginx/sites-enabled'.format(SITE_NAME))
    run('sudo systemctl restart nginx')


def _setup_cron_to_renew_letsencrypt(deploy_tools_folder):
    run("echo '15 3 * * * /usr/bin/letsencrypt renew'|crontab")


def _initial_db_migration(source_folder):
    venv_python = '/home/{}/.virtualenvs/{}/bin/python3'.format(
        USER_NAME, VENV_NAME)
    run('{} {}/manage.py makemigrations'.format(venv_python, source_folder))
    run('{} {}/manage.py migrate --noinput'.format(venv_python, source_folder))
    run('{} {}/manage.py collectstatic --noinput'.format(venv_python, source_folder))
    run('{} {}/manage.py createsuperuser --username={} --email={}@{}'.format(
        venv_python, source_folder, USER_NAME, USER_NAME, SITE_NAME))


def _restart_gunicorn():
    run('sudo systemctl restart gunicorn')
