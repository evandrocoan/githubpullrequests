# Create Pull Requests

Create pull requests programmatically using the GitHub API.

Created as a local alternative to:
1. https://github.com/backstrokeapp/server/issues/102#issuecomment-451306979 Stopped working a few days ago with Recived an error: undefined
1. https://github.com/wei/pull/issues/76#issue-397123888 Do not reset hard my default branch


### Installation

Either clone this repository and run `python setup.py develop` or just use `pip install githubpullrequests`


### Usage

```
$ githubpullrequests -h
usage: githubpullrequests [-h] [-f FILE] [-t TOKEN] [-mr MAXIMUM_REPOSITORIES]
                          [-c] [-d] [-s] [-ei ENABLE_ISSUES] [-as ADD_STARS]
                          [-wa WATCH_ALL]

Create Pull Requests, using GitHub API and a list of repositories.

optional arguments:
  -h, --help            show this help message and exit
  -f FILE, --file FILE  The file with the repositories informations
  -t TOKEN, --token TOKEN
                        GitHub token with `public_repos` access, or the path
                        to a file with the Github token in plain text. The
                        only contents the file can have is the token,
                        optionally with a trailing new line.
  -mr MAXIMUM_REPOSITORIES, --maximum-repositories MAXIMUM_REPOSITORIES
                        The maximum count of repositories/requests to process
                        per file.
  -c, --cancel-operation
                        If there is some batch operation running, cancel it as
                        soons as possible.
  -d, --dry-run         Do a rehearsal of a performance or procedure instead
                        of the real one i.e., do not create any pull requests,
                        but simulates/pretends to do so.
  -s, --synced-repositories
                        Reports which repositories not Synchronized with Pull
                        Requests. This also resets/skips any last session
                        saved due old throw/raised exceptions, because to
                        compute correctly the repositories list, it is
                        required to know all available repositories.
  -ei ENABLE_ISSUES, --enable-issues ENABLE_ISSUES
                        Enable the issue tracker on all repositories for the
                        given user.
  -as ADD_STARS, --add-stars ADD_STARS
                        Add a star on all repositories for the given user.
  -wa WATCH_ALL, --watch-all WATCH_ALL
                        Enable watch for all repositories on the given user.
```

For example:
```
$ githubpullrequests -f repositories_list.txt
```

Example of `repositories_list.txt`:
```config
[Anything Unique like evandrocoan/SublimePackageDefault]
    url = https://github.com/evandrocoan/SublimePackageDefault
    upstream = https://github.com/evandroforks/SublimePackageDefault
    branches = upstream_branch_name->fork_branch_name,
```

You need to define the environment variable `GITHUBPULLREQUESTS_TOKEN` with the GitHub access token with `public_repos` permission,
or pass the command line argument `-t token` to `githubpullrequests`.

1. https://stackoverflow.com/questions/47467039/how-to-create-github-pull-request-using-curl
1. https://stackoverflow.com/questions/28391901/using-the-github-api-create-git-pull-request-without-checking-out-the-code


# License

See the file [LICENSE.txt](LICENSE.txt)

