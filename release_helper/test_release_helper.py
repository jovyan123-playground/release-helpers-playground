# Copyright (c) Jupyter Development Team.
# Distributed under the terms of the Modified BSD License.
import json
import os
import os.path as osp
import re
import shlex
import shutil
import sys
from glob import glob
from pathlib import Path
from unittest.mock import call
from unittest.mock import MagicMock
from unittest.mock import patch
from unittest.mock import PropertyMock

from click.testing import CliRunner
from github.Commit import Commit
from github.GitRelease import GitRelease
from github.GitReleaseAsset import GitReleaseAsset
from github.NamedUser import NamedUser
from github.PaginatedList import PaginatedList
from github.PullRequest import PullRequest
from github.Repository import Repository
from github.Requester import Requester
from github.Tag import Tag
from github.Workflow import Workflow
from pytest import fixture

from release_helper import cli
from release_helper.cli import bump_version
from release_helper.cli import normalize_path
from release_helper.cli import run


VERSION_SPEC = "1.0.1"

PR_ENTRY = "Mention the required GITHUB_ACCESS_TOKEN [#1](https://github.com/executablebooks/github-activity/pull/1) ([@consideRatio](https://github.com/consideRatio))"

CHANGELOG_ENTRY = f"""
# master@{{2019-09-01}}...master@{{2019-11-01}}

([full changelog](https://github.com/executablebooks/github-activity/compare/479cc4b2f5504945021e3c4ee84818a10fabf810...ed7f1ed78b523c6b9fe6b3ac29e834087e299296))

## Merged PRs

* defining contributions [#14](https://github.com/executablebooks/github-activity/pull/14) ([@choldgraf](https://github.com/choldgraf))
* updating CLI for new tags [#12](https://github.com/executablebooks/github-activity/pull/12) ([@choldgraf](https://github.com/choldgraf))
* fixing link to changelog with refs [#11](https://github.com/executablebooks/github-activity/pull/11) ([@choldgraf](https://github.com/choldgraf))
* adding contributors list [#10](https://github.com/executablebooks/github-activity/pull/10) ([@choldgraf](https://github.com/choldgraf))
* some improvements to `since` and opened issues list [#8](https://github.com/executablebooks/github-activity/pull/8) ([@choldgraf](https://github.com/choldgraf))
* Support git references etc. [#6](https://github.com/executablebooks/github-activity/pull/6) ([@consideRatio](https://github.com/consideRatio))
* adding authentication information [#2](https://github.com/executablebooks/github-activity/pull/2) ([@choldgraf](https://github.com/choldgraf))
* {PR_ENTRY}

## Contributors to this release

([GitHub contributors page for this release](https://github.com/executablebooks/github-activity/graphs/contributors?from=2019-09-01&to=2019-11-01&type=c))

[@betatim](https://github.com/search?q=repo%3Aexecutablebooks%2Fgithub-activity+involves%3Abetatim+updated%3A2019-09-01..2019-11-01&type=Issues) | [@choldgraf](https://github.com/search?q=repo%3Aexecutablebooks%2Fgithub-activity+involves%3Acholdgraf+updated%3A2019-09-01..2019-11-01&type=Issues) | [@consideRatio](https://github.com/search?q=repo%3Aexecutablebooks%2Fgithub-activity+involves%3AconsideRatio+updated%3A2019-09-01..2019-11-01&type=Issues)
"""

SETUP_CFG_TEMPLATE = """
[metadata]
name = foo
version = attr: foo.__version__
description = My package description
long_description = file: README.md
long_description_content_type = text/markdown
license = BSD 3-Clause License
author = foo
author_email = foo@foo.com
url = http://foo.com

[options]
zip_safe = False
include_package_data = True
py_modules = foo
"""

SETUP_PY_TEMPLATE = """__import__("setuptools").setup()\n"""


PYPROJECT_TEMPLATE = """
[build-system]
requires = ["setuptools>=40.8.0", "wheel"]
build-backend = "setuptools.build_meta"
"""

PY_MODULE_TEMPLATE = '__version__ = "0.0.1"\n'

TBUMP_BASE_TEMPLATE = r"""
[version]
current = "0.0.1"
regex = '''
  (?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)
  ((?P<channel>a|b|rc|.dev)(?P<release>\d+))?
'''

[git]
message_template = "Bump to {new_version}"
tag_template = "v{new_version}"
"""

TBUMP_PY_TEMPLATE = """
[[file]]
src = "foo.py"
"""

TBUMP_NPM_TEMPLATE = """
[[file]]
src = "package.json"
search = '"version": "{current_version}"'
"""

MANIFEST_TEMPLATE = """
include *.md
include *.toml
include *.yaml
"""

CHANGELOG_TEMPLATE = f"""# Changelog

{cli.START_MARKER}

{cli.END_MARKER}

## 0.0.1

Initial commit
"""


@fixture(autouse=True)
def mock_env_vars(mocker):
    """Clear any GitHub related environment variables"""
    env = os.environ.copy()
    for key in list(env.keys()):
        if key.startswith("GITHUB_"):
            del env[key]
    mocker.patch.dict(os.environ, env, clear=True)
    yield


@fixture
def git_repo(tmp_path):
    prev_dir = os.getcwd()
    os.chdir(tmp_path)

    run("git init")
    run("git config user.name snuffy")
    run("git config user.email snuffy@sesame.com")

    run("git checkout -b foo")
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("dist/*\nbuild/*\n", encoding="utf-8")
    run("git add .")
    run('git commit -m "foo"')
    run("git tag v0.0.1")
    run(f"git remote add upstream {normalize_path(tmp_path)}")

    yield tmp_path
    os.chdir(prev_dir)


def create_python_package(git_repo):
    setuppy = git_repo / "setup.py"
    setuppy.write_text(SETUP_PY_TEMPLATE, encoding="utf-8")

    setuppy = git_repo / "setup.cfg"
    setuppy.write_text(SETUP_CFG_TEMPLATE, encoding="utf-8")

    tbump = git_repo / "tbump.toml"
    tbump.write_text(TBUMP_BASE_TEMPLATE + TBUMP_PY_TEMPLATE, encoding="utf-8")

    pyproject = git_repo / "pyproject.toml"
    pyproject.write_text(PYPROJECT_TEMPLATE, encoding="utf-8")

    readme = git_repo / "README.md"
    readme.write_text("Hello from foo project\n", encoding="utf-8")

    foopy = git_repo / "foo.py"
    foopy.write_text(PY_MODULE_TEMPLATE, encoding="utf-8")

    changelog = git_repo / "CHANGELOG.md"
    changelog.write_text(CHANGELOG_TEMPLATE, encoding="utf-8")

    manifest = git_repo / "MANIFEST.in"
    manifest.write_text(MANIFEST_TEMPLATE, encoding="utf-8")

    here = Path(__file__).parent
    text = here.parent.joinpath(".pre-commit-config.yaml").read_text(encoding="utf-8")

    pre_commit = git_repo / ".pre-commit-config.yaml"
    pre_commit.write_text(text, encoding="utf-8")

    run("git add .")
    run('git commit -m "initial python package"')
    return git_repo


def create_npm_package(git_repo):
    npm = normalize_path(shutil.which("npm"))
    run(f"{npm} init -y")
    git_repo.joinpath("index.js").write_text('console.log("hello")', encoding="utf-8")
    run("git add .")
    run('git commit -m "initial npm package"')
    return git_repo


@fixture
def py_package(git_repo):
    pkg = create_python_package(git_repo)
    run("git checkout -b bar foo")
    return pkg


@fixture
def npm_package(git_repo):
    pkg = create_npm_package(git_repo)
    run("git checkout -b bar foo")
    return pkg


@fixture()
def runner():
    cli_runner = CliRunner()

    def run(*args, **kwargs):
        result = cli_runner.invoke(cli.main, *args, **kwargs)
        assert result.exit_code == 0, result.output
        return result

    return run


@fixture()
def pkg_env(py_package, runner):
    runner(["prep-env", "--version-spec", VERSION_SPEC])
    return py_package


@fixture()
def changelog_entry(pkg_env, runner, mocker):
    changelog = pkg_env / "CHANGELOG.md"
    mocked_gen = mocker.patch("release_helper.cli.generate_activity_md")
    mocked_gen.return_value = CHANGELOG_ENTRY
    runner(["prep-changelog", "--changelog-path", changelog])
    return changelog


def test_get_branch(git_repo):
    assert cli.get_branch() == "foo"


def test_get_repo(git_repo, mocker):
    repo = f"{git_repo.parent.name}/{git_repo.name}"
    assert cli.get_repo("upstream") == repo


def test_get_version_python(py_package):
    assert cli.get_version() == "0.0.1"
    bump_version("0.0.2a0")
    assert cli.get_version() == "0.0.2a0"


def test_get_version_npm(npm_package):
    assert cli.get_version() == "1.0.0"
    npm = normalize_path(shutil.which("npm"))
    run(f"{npm} version patch")
    assert cli.get_version() == "1.0.1"


def test_format_pr_entry(mocker):
    gh_repo = Repository(None, dict(), dict(), True)
    pull = PullRequest(None, dict(), dict(), True)
    user = NamedUser(None, dict(), dict(), True)
    gh_repo.get_pull = mock = MagicMock(return_value=pull)
    mock_method = mocker.patch.object(cli.Github, "get_repo", return_value=gh_repo)
    mock_user = mocker.patch(
        "github.PullRequest.PullRequest.user", new_callable=PropertyMock
    )
    mock_user.return_value = user
    resp = cli.format_pr_entry("foo", 121, auth="baz")
    mock_method.assert_called_with("foo")
    mock.assert_called_once()

    assert resp.startswith("- ")


def test_get_changelog_entry(py_package, mocker):
    version = cli.get_version()

    mocked_gen = mocker.patch("release_helper.cli.generate_activity_md")
    mocked_gen.return_value = CHANGELOG_ENTRY
    resp = cli.get_changelog_entry("foo", "bar/baz", version)
    mocked_gen.assert_called_with("bar/baz", since="v0.0.1", kind="pr", auth=None)

    assert f"## {version}" in resp
    assert PR_ENTRY in resp

    mocked_gen.return_value = CHANGELOG_ENTRY
    resp = cli.get_changelog_entry(
        "foo", "bar/baz", version, resolve_backports=True, auth="bizz"
    )
    mocked_gen.assert_called_with("bar/baz", since="v0.0.1", kind="pr", auth="bizz")

    assert f"## {version}" in resp
    assert PR_ENTRY in resp


def test_compute_sha256(py_package):
    assert len(cli.compute_sha256(py_package / "CHANGELOG.md")) == 64


def test_create_release_commit(py_package):
    bump_version("0.0.2a0")
    version = cli.get_version()
    run("python -m build .")
    shas = cli.create_release_commit(version)
    assert normalize_path("dist/foo-0.0.2a0.tar.gz") in shas
    assert normalize_path("dist/foo-0.0.2a0-py3-none-any.whl") in shas
    shutil.rmtree(py_package / "dist")

    # Add an npm package and test with that
    create_npm_package(py_package)
    pkg_json = py_package / "package.json"
    data = json.loads(pkg_json.read_text(encoding="utf-8"))
    data["version"] = version
    pkg_json.write_text(json.dumps(data, indent=4), encoding="utf-8")
    txt = (py_package / "tbump.toml").read_text(encoding="utf-8")
    txt += TBUMP_NPM_TEMPLATE
    (py_package / "tbump.toml").write_text(txt, encoding="utf-8")
    bump_version("0.0.2a1")
    version = cli.get_version()
    run("python -m build .")
    shas = cli.create_release_commit(version)
    assert len(shas) == 3
    assert normalize_path("dist/foo-0.0.2a1.tar.gz") in shas


def test_bump_version(py_package):
    for spec in ["1.0.1", "1.0.1.dev1", "1.0.3a4"]:
        bump_version(spec)
        assert cli.get_version() == spec


def test_prep_env_simple(py_package, runner):
    """Standard local run with no env variables."""
    result = runner(["prep-env", "--version-spec", "1.0.1"], env=dict(GITHUB_ACTION=""))
    assert "branch=bar" in result.output
    assert "version=1.0.1" in result.output
    assert "is_prerelease=false" in result.output


def test_prep_env_pr(py_package, runner):
    """With GITHUB_BASE_REF (Pull Request)"""
    env = dict(GITHUB_BASE_REF="foo", VERSION_SPEC="1.0.1", GITHUB_ACTION="")
    result = runner(["prep-env"], env=env)
    assert "branch=foo" in result.output


def test_prep_env_full(py_package, tmp_path, mocker, runner):
    """Full GitHub Actions simulation (Push)"""
    version_spec = "1.0.1a1"

    env_file = tmp_path / "github.env"

    env = dict(
        GITHUB_REF="refs/heads/foo",
        GITHUB_WORKFLOW="check-release",
        GITHUB_ACTIONS="true",
        GITHUB_REPOSITORY="baz/bar",
        VERSION_SPEC=version_spec,
        GITHUB_ENV=str(env_file),
        GITHUB_ACTOR="snuffy",
        GITHUB_ACCESS_TOKEN="abc123",
    )

    # Fake out the version and source repo responses
    mock_run = mocker.patch("release_helper.cli.run")
    mock_run.return_value = version_spec
    repo = Repository(None, dict(), dict(), True)
    mocked_method = mocker.patch.object(cli.Github, "get_repo", return_value=repo)

    runner(["prep-env"], env=env)

    mock_run.assert_has_calls(
        [
            call(
                'git config --global user.email "41898282+github-actions[bot]@users.noreply.github.com"'
            ),
            call('git config --global user.name "GitHub Action"'),
            call("git remote"),
            call("git remote add upstream http://snuffy:abc123@github.com/baz/bar.git"),
            call("git fetch upstream foo --tags"),
            call("git branch"),
            call("git checkout -B foo upstream/foo"),
            call("tbump --non-interactive --only-patch 1.0.1a1"),
            call("python setup.py --version"),
        ]
    )
    text = env_file.read_text(encoding="utf-8")
    assert "BRANCH=foo" in text
    assert f"VERSION={version_spec}" in text
    assert "IS_PRERELEASE=true" in text
    assert "REPOSITORY=baz/bar" in text


def test_prep_changelog(py_package, mocker, runner):
    run("pre-commit run -a")

    changelog = py_package / "CHANGELOG.md"

    runner(["prep-env", "--version-spec", VERSION_SPEC])

    mocked_gen = mocker.patch("release_helper.cli.generate_activity_md")
    mocked_gen.return_value = CHANGELOG_ENTRY
    runner(["prep-changelog", "--changelog-path", changelog])
    text = changelog.read_text(encoding="utf-8")
    assert cli.START_MARKER in text
    assert cli.END_MARKER in text
    assert PR_ENTRY in text

    assert len(re.findall(cli.START_MARKER, text)) == 1
    assert len(re.findall(cli.END_MARKER, text)) == 1

    run("pre-commit run -a")


def test_prep_changelog_existing(py_package, mocker, runner):
    changelog = py_package / "CHANGELOG.md"

    runner(["prep-env", "--version-spec", VERSION_SPEC])

    mocked_gen = mocker.patch("release_helper.cli.generate_activity_md")
    mocked_gen.return_value = CHANGELOG_ENTRY
    runner(["prep-changelog", "--changelog-path", changelog])
    text = changelog.read_text(encoding="utf-8")
    text = text.replace("defining contributions", "Definining contributions")
    changelog.write_text(text, encoding="utf-8")

    # Commit the change
    run('git commit -a -m "commit changelog"')

    mocked_gen.return_value = CHANGELOG_ENTRY
    runner(["prep-changelog", "--changelog-path", changelog])
    text = changelog.read_text(encoding="utf-8")
    assert "Definining contributions" in text, text
    assert not "defining contributions" in text, text

    assert len(re.findall(cli.START_MARKER, text)) == 1
    assert len(re.findall(cli.END_MARKER, text)) == 1

    run("pre-commit run -a")


def test_publish_changelog_full(py_package, mocker, runner, changelog_entry):
    repo = Repository(None, dict(), dict(), True)
    pull = PullRequest(None, dict(), dict(), True)

    mocked_method = mocker.patch.object(cli.Github, "get_repo", return_value=repo)
    repo.create_pull = pull_mock = MagicMock(return_value=pull)

    runner(["publish-changelog"])
    pull_mock.assert_called_once()


def test_publish_changelog_dry_run(py_package, mocker, runner, changelog_entry):
    repo = Repository(None, dict(), dict(), True)
    pull = PullRequest(None, dict(), dict(), True)

    mocked_method = mocker.patch.object(cli.Github, "get_repo", return_value=repo)
    repo.create_pull = pull_mock = MagicMock(return_value=pull)

    runner(["publish-changelog", "--dry-run"])
    pull_mock.assert_not_called()


def test_check_md_links(py_package, runner):
    readme = py_package / "README.md"
    text = readme.read_text(encoding="utf-8")
    text += "\nhttps://apod.nasa.gov/apod/astropix.html"
    readme.write_text(text, encoding="utf-8")

    runner(["check-md-links"])

    foo = py_package / "FOO.md"
    foo.write_text("http://127.0.0.1:5555")

    runner(["check-md-links", "--ignore", "FOO.md"])


def test_check_changelog(py_package, tmp_path, mocker, runner, changelog_entry):
    output = tmp_path / "output.md"

    # prep the release
    bump_version(VERSION_SPEC)

    runner(
        ["check-changelog", "--changelog-path", changelog_entry, "--output", output],
    )

    assert PR_ENTRY in output.read_text(encoding="utf-8")
    text = changelog_entry.read_text(encoding="utf-8")
    assert f"{cli.START_MARKER}\n\n## {VERSION_SPEC}" in text
    assert cli.END_MARKER in text


def test_build_python(py_package, runner):
    runner(["build-python"])


def test_check_python(py_package, runner):
    runner(["build-python"])
    dist_files = glob(str(py_package / "dist" / "*"))
    runner(["check-python"] + dist_files)


def test_handle_npm(npm_package, runner):
    runner(["handle-npm"])


def test_check_manifest(py_package, runner):
    runner(["check-manifest"])


def test_tag_release(pkg_env, runner):
    # Create the dist files
    run("python -m build .")
    # Tag the release
    runner(["tag-release"])


def make_release_mock(mocker):
    repo = Repository(None, dict(), dict(), True)
    url = "https://github.com/foo/bar/releases/tag/v0.0.1"
    release = GitRelease(None, dict(), dict(html_url=url), True)
    asset = GitReleaseAsset(None, dict(), dict(), True)
    asset.delete_asset = delete_mock = MagicMock()
    release.get_assets = MagicMock(return_value=[asset])
    release.upload_asset = upload_mock = MagicMock(return_value=asset)
    repo.create_git_release = create_mock = MagicMock(return_value=release)
    repo.get_release = create_mock

    mock_method = mocker.patch.object(cli.Github, "get_repo", return_value=repo)
    release.upload_mock = upload_mock
    release.delete_mock = delete_mock
    release.create_mock = create_mock
    return release


def test_publish_release_draft(changelog_entry, mocker, runner):
    # Create the dist files
    run("python -m build .")

    # Finalize the release
    runner(["tag-release"])

    # Publish the release - dry run
    release = make_release_mock(mocker)

    runner(["publish-release", "--dry-run"] + glob("dist/*"))

    release.create_mock.assert_called_once()
    release.upload_mock.assert_has_calls(
        [
            call("dist/foo-1.0.1-py3-none-any.whl", label=""),
            call("dist/foo-1.0.1.tar.gz", label=""),
        ]
    )
    release.delete_mock.assert_not_called()


def test_publish_release_final(npm_package, runner, mocker):
    # Create the dist files
    cli.bump_version(VERSION_SPEC)
    runner(["handle-npm"])

    # Finalize the release
    runner(["tag-release"])

    # Publish the release
    release = make_release_mock(mocker)

    runner(
        ["publish-release"] + glob("dist/*"),
    )
    release.create_mock.assert_called_once()
    release.upload_mock.assert_has_calls(
        [call("dist/test_publish_release_final0-1.0.1.tgz", label="")]
    )
    release.delete_mock.assert_not_called()


def test_delete_release(npm_package, runner, mocker):
    # Create the dist files
    cli.bump_version(VERSION_SPEC)
    runner(["handle-npm"])

    # Finalize the release
    runner(["tag-release"])

    # Publish the release
    release = make_release_mock(mocker)
    result = runner(["publish-release", "--dry-run"] + glob("dist/*"))

    url = ""
    for line in result.output.splitlines():
        match = re.match(r"::set-output name=url::(.*)", line)
        if match:
            url = match.groups()[0]

    # Delete the release
    release.delete_release = delete_mock = MagicMock()

    runner(["delete-release", url])
    release.delete_mock.assert_called_with()
    delete_mock.assert_called_once()


class MockReponse:
    def __init__(self, filename):
        self.filename = filename

    def raise_for_status(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, *args, **kwargs):
        with open(self.filename, "rb") as fid:
            return [fid.read()]


def gh_release(sha, version, mocker):
    tag_name = f"v{version}"
    url = f"https://github.com/foo/bar/releases/tag/{tag_name}"

    branch = cli.get_branch()
    repo = Repository(None, dict(), dict(url=normalize_path(os.getcwd())), True)
    release = GitRelease(
        None, dict(), dict(target_commitish=branch, tag_name=tag_name, url=url), True
    )
    repo.get_release = MagicMock(return_value=release)

    commit = Commit(None, dict(), dict(sha=sha), True)
    tag = Tag(None, dict(), dict(name=tag_name), True)
    mock_commit = mocker.patch("github.Tag.Tag.commit", new_callable=PropertyMock)
    mock_commit.return_value = commit
    repo.get_tags = MagicMock(return_value=[tag])
    mock_method = mocker.patch.object(cli.Github, "get_repo", return_value=repo)

    return release


def test_publish_dist_py(py_package, runner, mocker):
    version = "0.0.2"
    cli.bump_version(version)

    # Create the dist files
    run("python -m build .")

    # Create a tag with shas
    runner(["tag-release"])
    sha = run("git rev-parse HEAD")

    # Make the release mock
    release = gh_release(sha, version, mocker)

    sdist_name = osp.basename(glob("dist/*.gz")[0])
    wheel_name = osp.basename(glob("dist/*.whl")[0])
    sdist = GitReleaseAsset(
        None, dict(), dict(name=sdist_name, url="http://foo.com"), True
    )
    wheel = GitReleaseAsset(
        None, dict(), dict(name=wheel_name, url="http://bar.com"), True
    )
    release.get_assets = MagicMock(return_value=[sdist, wheel])

    sdist_resp = MockReponse(Path("dist") / sdist_name)
    wheel_resp = MockReponse(Path("dist") / wheel_name)
    get_mock = mocker.patch("requests.get", side_effect=[sdist_resp, wheel_resp])

    orig_run = cli.run
    called = 0

    def wrapped(cmd, **kwargs):
        nonlocal called
        if cmd.startswith("twine upload"):
            called += 1
            return ""
        return orig_run(cmd, **kwargs)

    mock_run = mocker.patch("release_helper.cli.run", wraps=wrapped)

    release.update_release = update_mock = MagicMock()
    runner(["publish-dist", release.url])
    update_mock.assert_called_once()
    assert called == 2, called


def test_publish_dist_npm(npm_package, runner, mocker):
    version = "0.0.2"
    cli.bump_version(version)

    # Create the dist files
    runner(["handle-npm"])

    # Create a tag with shas
    runner(["tag-release"])
    sha = run("git rev-parse HEAD")

    # Make the release mock
    release = gh_release(sha, version, mocker)

    dist_name = osp.basename(glob("dist/*.tgz")[0])
    dist = GitReleaseAsset(
        None, dict(), dict(name=dist_name, url="http://foo.com"), True
    )
    release.get_assets = MagicMock(return_value=[dist])

    dist_resp = MockReponse(Path("dist") / dist_name)
    get_mock = mocker.patch("requests.get", side_effect=[dist_resp])

    orig_run = cli.run
    called = 0

    def wrapped(cmd, **kwargs):
        nonlocal called
        if cmd.startswith("npm publish"):
            called += 1
            return ""
        return orig_run(cmd, **kwargs)

    mock_run = mocker.patch("release_helper.cli.run", wraps=wrapped)
    release.update_release = update_mock = MagicMock()
    runner(["publish-dist", release.url])
    update_mock.assert_called_once()
    assert called == 1, called
