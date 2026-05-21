import argparse
import hashlib
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
VENV_DIR = ROOT / ".venv"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
REQUIREMENTS_HASH_FILE = VENV_DIR / '.requirements-hash'
PYTHON = sys.executable


def read_dotenv(path: Path) -> dict:
    if not path.exists():
        return {}
    data = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in stripped:
            continue
        key, value = stripped.split('=', 1)
        data[key.strip()] = value.strip()
    return data


def write_dotenv(path: Path, values: dict):
    lines = []
    for key, val in values.items():
        if val is None:
            val = ''
        lines.append(f"{key}={val}")
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def copy_example_env():
    if ENV_EXAMPLE.exists():
        shutil.copy2(ENV_EXAMPLE, ENV_FILE)
        print(f"Created {ENV_FILE} from {ENV_EXAMPLE}")
        return True
    return False


def ensure_env_file():
    if ENV_FILE.exists():
        return
    if copy_example_env():
        values = read_dotenv(ENV_FILE)
    else:
        values = {
            'SECRET_KEY': '',
            'DEBUG': 'True',
            'ALLOWED_HOSTS': '127.0.0.1,localhost',
            'BOOTSTRAP_SUPERADMIN': 'False',
            'BOOTSTRAP_SUPERADMIN_USERNAME': 'admin',
            'BOOTSTRAP_SUPERADMIN_PASSWORD': '',
            'BOOTSTRAP_SUPERADMIN_EMAIL': 'admin@example.com',
            'TWILIO_ACCOUNT_SID': 'ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
            'TWILIO_AUTH_TOKEN': 'your_auth_token',
            'TWILIO_PHONE_NUMBER': '+15017122661',
            'DEFAULT_FROM_EMAIL': 'webmaster@yourdomain.com',
            'USE_S3': 'False',
            'AWS_ACCESS_KEY_ID': '',
            'AWS_SECRET_ACCESS_KEY': '',
            'AWS_STORAGE_BUCKET_NAME': '',
            'AWS_S3_REGION_NAME': 'us-east-1',
        }

    if not values.get('SECRET_KEY'):
        values['SECRET_KEY'] = secrets.token_urlsafe(50)

    if not values.get('DEBUG'):
        values['DEBUG'] = 'True'

    write_dotenv(ENV_FILE, values)
    print(f"Created .env file at {ENV_FILE}. Please review and edit it if needed.")
    print("If you are deploying to production, set DEBUG=False and use a real SECRET_KEY, database, and secrets.")


def ensure_venv():
    if VENV_DIR.exists() and ((VENV_DIR / 'Scripts' / 'python.exe').exists() or (VENV_DIR / 'bin' / 'python').exists()):
        return False
    print('Creating virtual environment...')
    subprocess.check_call([PYTHON, '-m', 'venv', str(VENV_DIR)])
    return True


def venv_python() -> str:
    if os.name == 'nt':
        return str(VENV_DIR / 'Scripts' / 'python.exe')
    return str(VENV_DIR / 'bin' / 'python')


def venv_pip() -> str:
    if os.name == 'nt':
        return str(VENV_DIR / 'Scripts' / 'pip.exe')
    return str(VENV_DIR / 'bin' / 'pip')


def run_cmd(cmd, env=None, cwd=ROOT, check=True):
    print('Running:', ' '.join(cmd))
    result = subprocess.run(cmd, cwd=cwd, env=env or os.environ, shell=False)
    if check and result.returncode != 0:
        raise SystemExit(result.returncode)
    return result.returncode


def load_env_to_os(env_path: Path):
    values = read_dotenv(env_path)
    for key, value in values.items():
        if key not in os.environ:
            os.environ[key] = value
    return values


def get_requirements_hash() -> str:
    content = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def read_saved_requirements_hash() -> str | None:
    try:
        return REQUIREMENTS_HASH_FILE.read_text(encoding='utf-8').strip()
    except FileNotFoundError:
        return None


def write_requirements_hash(hash_value: str):
    REQUIREMENTS_HASH_FILE.parent.mkdir(parents=True, exist_ok=True)
    REQUIREMENTS_HASH_FILE.write_text(hash_value + '\n', encoding='utf-8')


def install_requirements():
    print('Installing Python dependencies...')
    cmd = [
        venv_python(),
        '-m', 'pip',
        'install',
        '--disable-pip-version-check',
        '--upgrade-strategy',
        'only-if-needed',
        '-r',
        'requirements.txt',
    ]
    run_cmd(cmd)


def upgrade_pip():
    print('Preparing Python dependencies...')
    run_cmd([venv_python(), '-m', 'pip', 'install', '--disable-pip-version-check', '--upgrade', 'pip'])


def run_manage(command, env=None):
    env = env or os.environ.copy()
    cmd = [venv_python(), 'manage.py'] + command
    return run_cmd(cmd, env=env)


def maybe_prompt_superadmin(values):
    if values.get('BOOTSTRAP_SUPERADMIN', '').lower() != 'true':
        return
    if values.get('BOOTSTRAP_SUPERADMIN_PASSWORD'):
        return
    print('BOOTSTRAP_SUPERADMIN is enabled, but BOOTSTRAP_SUPERADMIN_PASSWORD is not set.')
    password = input('Enter a strong superadmin password (or leave blank to auto-generate): ').strip()
    if not password:
        password = secrets.token_urlsafe(16)
        print('Generated password for bootstrap superadmin:', password)
    values['BOOTSTRAP_SUPERADMIN_PASSWORD'] = password
    write_dotenv(ENV_FILE, values)
    print('Updated .env with BOOTSTRAP_SUPERADMIN_PASSWORD.')


def main():
    parser = argparse.ArgumentParser(description='Setup environment and migrate the Django app.')
    parser.add_argument('--serve', action='store_true', help='Start the development server after setup')
    parser.add_argument('--prod', action='store_true', help='Use gunicorn instead of runserver if available')
    parser.add_argument('--refresh-deps', action='store_true', help='Force a dependency reinstall even if requirements.txt is unchanged')
    parser.add_argument('--upgrade-pip', action='store_true', help='Upgrade pip inside the project virtual environment before installing dependencies')
    args = parser.parse_args()

    ensure_env_file()
    venv_created = ensure_venv()

    current_hash = get_requirements_hash()
    previous_hash = read_saved_requirements_hash()
    deps_changed = (not REQUIREMENTS_HASH_FILE.exists()) or previous_hash != current_hash
    if args.upgrade_pip or venv_created:
        upgrade_pip()
    if args.refresh_deps or deps_changed:
        if args.refresh_deps and not deps_changed:
            print('Requirements file is unchanged, but dependency refresh was requested.')
        elif deps_changed and previous_hash:
            print('requirements.txt changed. Syncing only missing or required packages...')
        else:
            print('Installing project dependencies for the first time...')
        install_requirements()
        write_requirements_hash(current_hash)
    else:
        print('Virtual environment already set up. Skipping dependency install.')

    values = load_env_to_os(ENV_FILE)
    maybe_prompt_superadmin(values)

    print('Checking migrations...')
    makemigration_cmd = [venv_python(), 'manage.py', 'makemigrations', '--check', '--dry-run']
    rc = subprocess.run(makemigration_cmd, cwd=ROOT, env=os.environ).returncode
    if rc != 0:
        print('Creating missing migrations...')
        run_manage(['makemigrations'])

    print('Applying migrations...')
    run_manage(['migrate', '--noinput'])

    print('Collecting static files...')
    run_manage(['collectstatic', '--noinput'])

    if values.get('BOOTSTRAP_SUPERADMIN', '').lower() == 'true':
        print('Bootstrapping superadmin account...')
        run_manage(['bootstrap_superadmin'])

    if args.serve:
        if args.prod:
            print('Starting production server with gunicorn...')
            run_cmd([venv_python(), '-m', 'gunicorn', 'bjs_management.wsgi:application', '--bind', '0.0.0.0:8000', '--workers', '3'])
        else:
            print('Starting Django development server...')
            run_manage(['runserver'])
    else:
        print('Setup complete. You can now run the server manually if desired.')


if __name__ == '__main__':
    main()
