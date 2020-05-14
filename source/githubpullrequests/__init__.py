#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

####################### Licensing #######################################################
#
# Create Pull Requests, using GitHub API and a list of repositories
# Copyright (C) 2019 Evandro Coan <https://github.com/evandrocoan>
#
#  Redistributions of source code must retain the above
#  copyright notice, this list of conditions and the
#  following disclaimer.
#
#  Redistributions in binary form must reproduce the above
#  copyright notice, this list of conditions and the following
#  disclaimer in the documentation and/or other materials
#  provided with the distribution.
#
#  Neither the name Evandro Coan nor the names of any
#  contributors may be used to endorse or promote products
#  derived from this software without specific prior written
#  permission.
#
#  This program is free software; you can redistribute it and/or modify it
#  under the terms of the GNU General Public License as published by the
#  Free Software Foundation; either version 3 of the License, or ( at
#  your option ) any later version.
#
#  This program is distributed in the hope that it will be useful, but
#  WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
#  General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#########################################################################################
#

import os
import io
import re
import json
import time

import github
import requests
import argparse
import contextlib

try:
    import configparser

except( ImportError, ValueError ):
    from six.moves import configparser

from collections import OrderedDict

from debug_tools import getLogger
from debug_tools.utilities import wrap_text
from debug_tools.utilities import pop_dict_last_item
from debug_tools.utilities import move_to_dict_beginning
from debug_tools.third_part import get_section_option
from debug_tools.estimated_time_left import sequence_timer
from debug_tools.estimated_time_left import progress_info

PACKAGE_ROOT_DIRECTORY = os.path.dirname( os.path.realpath( __file__ ) )
CHANNEL_SESSION_FILE = os.path.join( PACKAGE_ROOT_DIRECTORY, "last_session.json" )

headers = {}
MAXIMUM_WORSPACES_ENTRIES = 100

g_is_already_running = False
log = getLogger( 127, "" )


def main():
    github_token = os.environ.get( 'GITHUBPULLREQUESTS_TOKEN', "" ).strip()

    # https://stackoverflow.com/questions/6382804/how-to-use-getopt-optarg-in-python-how-to-shift
    argumentParser = argparse.ArgumentParser( description='Create Pull Requests, using GitHub API and a list of repositories.' )

    argumentParser.add_argument( "-f", "--file", action="append", default=[],
            help="The file with the repositories informations" )

    argumentParser.add_argument( "-t", "--token", action="store", default="",
            help="GitHub token with `public_repos` access, or the path "
            "to a file with the Github token in plain text. The only contents "
            "the file can have is the token, optionally with a trailing new line." )

    argumentParser.add_argument( "-mr", "--maximum-repositories", action="store", type=int, default=0,
            help="The maximum count of repositories/requests to process per file." )

    argumentParser.add_argument( "-c", "--cancel-operation", action="store_true", default=False,
            help="If there is some batch operation running, cancel it as soons as possible." )

    argumentParser.add_argument( "-d", "--dry-run", action="store_true", default=False,
            help="Do a rehearsal of a performance or procedure instead of the real one "
            "i.e., do not create any pull requests, but simulates/pretends to do so." )

    argumentParser.add_argument( "-s", "--synced-repositories", action="store_true", default=False,
            help="Reports which repositories not Synchronized with Pull Requests. "
            "This also resets/skips any last session saved due old throw/raised exceptions, "
            "because to compute correctly the repositories list, it is required to know all "
            "available repositories." )

    argumentParser.add_argument( "-ei", "--enable-issues", action="store", default="",
            help="Enable the issue tracker on all repositories for the given user." )

    argumentParser.add_argument( "-as", "--add-stars", action="store", default="",
            help="Add a star on all repositories for the given user." )

    argumentParser.add_argument( "-wa", "--watch-all", action="store", default="",
            help="Enable watch for all repositories on the given user." )

    argumentsNamespace = argumentParser.parse_args()
    # log( 1, argumentsNamespace )

    if argumentsNamespace.cancel_operation:
        free_mutex_lock()
        return

    if argumentsNamespace.token:
        github_token = argumentsNamespace.token

    if github_token:
        global headers
        if os.path.exists( github_token ):
            with open( github_token, 'r', ) as input_file:
                github_token = input_file.read()

        github_token = github_token.strip()
        headers = { "Authorization": f"Bearer {github_token}" }
        log_ratelimit(headers)

    else:
        log.clean( "Error: Missing required command line argument `-t/--token`" )
        argumentParser.print_help()
        return

    if argumentsNamespace.enable_issues:
        enable_github_issue_tracker( argumentsNamespace.enable_issues )

    if argumentsNamespace.add_stars:
        add_stars_on_github_repositories( argumentsNamespace.add_stars )

    if argumentsNamespace.watch_all:
        watch_all_github_repositories( argumentsNamespace.watch_all )

    if argumentsNamespace.file:
        pull_requester = PullRequester(
            github_token,
            argumentsNamespace.maximum_repositories,
            argumentsNamespace.synced_repositories,
            argumentsNamespace.dry_run
        )
        pull_requester.parse_gitmodules( argumentsNamespace.file )
        pull_requester.publish_report()

    log_ratelimit(headers)


class PullRequester(object):

    def __init__(self, github_token, maximum_repositories=0, synced_repositories=False, is_dry_run=False):
        super(PullRequester, self).__init__()
        self.is_dry_run = is_dry_run
        self.github_token = github_token

        if synced_repositories:
            self.lastSection = OrderedDict()

        else:
            try:
                with open( CHANNEL_SESSION_FILE, 'r' ) as data_file:
                    self.lastSection = json.load( data_file, object_pairs_hook=OrderedDict )

            except( IOError, ValueError ):
                self.lastSection = OrderedDict()

        self.maximum_repositories = maximum_repositories
        self.synced_repositories = synced_repositories

        self.last_module_file = None
        self.request_index = 0
        self.skipped_repositories = []
        self.init_report()

    def init_report(self):
        self.repositories_results = OrderedDict()
        self.skip_reasons = [
            'No commits between',
            'A pull request already exists',
            'Repository was archived',
            'has no history in common',
        ]

        for reason in self.skip_reasons:
            self.repositories_results[reason] = []

        self.downstream_users = set()
        self.parsed_repositories = set()
        self.full_parsed_repositories = {}

        self.repositories_results['Unknown Reason'] = []
        self.repositories_results['Successfully Created'] = []

        # using username and password
        # self.github_api = github.Github("user", "password")

        # or using an access token
        self.github_api = github.Github( self.github_token )

        # Github Enterprise with custom hostname
        # self.github_api = github.Github(base_url="https://{hostname}/api/v3", login_or_token="access_token")

    def parse_gitmodules(self, gitmodules_file):

        with lock_context_manager() as is_allowed:
            if not is_allowed: return

            try:
                if not isinstance( gitmodules_file, list ):
                    raise ValueError( "The gitmodules_file need to be an instance of list: `%s`" % gitmodules_file )

                self._parse_gitmodules( gitmodules_file )

            except:
                self._save_data( self.request_index - 1 )
                raise

            self._save_data( 0 )

        free_mutex_lock()

    def _save_data(self, index):
        if not self.last_module_file: return
        self.lastSection[self.last_module_file] = index

        move_to_dict_beginning( self.lastSection, self.last_module_file )
        while len( self.lastSection ) > MAXIMUM_WORSPACES_ENTRIES:
            pop_dict_last_item( self.lastSection )

        with open( CHANNEL_SESSION_FILE, 'w' ) as output_file:
            json.dump( self.lastSection, output_file, indent=4, separators=(',', ': ') )

    def _parse_gitmodules(self, gitmodules_file):
        sections_count = 0
        loaded_config_file = OrderedDict()

        for module_file in gitmodules_file:
            # https://stackoverflow.com/questions/45415684/how-to-stop-tabs-on-python-2-7-rawconfigparser-throwing-parsingerror/
            with open( module_file ) as fakeFile:
                # https://stackoverflow.com/questions/22316333/how-can-i-resolve-typeerror-with-stringio-in-python-2-7
                fakefile = io.StringIO( fakeFile.read().replace( u"\t", u"" ) )

            config_parser = configparser.RawConfigParser()
            config_parser._read( fakefile, module_file )
            sections_count += len( config_parser.sections() )
            loaded_config_file[module_file] = config_parser

        start_index = 0
        self.request_index = 0
        successful_resquests = 0

        def get_sections():
            for module_file, config_parser in loaded_config_file.items():
                for section in config_parser.sections():
                    yield section, module_file, config_parser

        self.last_module_file = ""

        for sections, pi in sequence_timer( get_sections(), info_frequency=0, length=sections_count ):
            section, module_file, config_parser = sections
            progress = progress_info( pi )
            self.request_index += 1
            self.request_index = self.request_index

            if self.last_module_file != module_file:
                self.last_module_file = module_file
                start_index = self.lastSection.get( module_file, 0 )

                log.newline(count=2)
                log( 1, 'module_file', module_file )

            if not g_is_already_running:
                raise ImportError( "Stopping the process as this Python module was reloaded!" )

            # Walk until the last processed index, skipping everything else
            if start_index > 0:
                start_index -= 1
                continue

            # For quick testing
            if self.maximum_repositories and self.request_index > self.maximum_repositories:
                break

            log.newline()
            log( 1, "{:s}, {:3d}({:d}) of {:d}...".format(
                    progress, self.request_index, successful_resquests, sections_count ) )

            downstream = get_section_option( section, "url", config_parser )
            upstream = get_section_option( section, "upstream", config_parser )

            upstream_user, upstream_repository = parse_github( upstream )
            downstream_user, downstream_repository = parse_github( downstream )
            downstream_name = "{}/{}".format( downstream_user, downstream_repository )

            branches = get_section_option( section, "branches", config_parser )
            local_branch, upstream_branch = parser_branches( branches )

            full_upstream_name = "{}/{}@{}".format( upstream_user, upstream_repository, upstream_branch )
            full_downstream_name = "{} -> {}".format( downstream_name, section )

            log( 1, branches )
            log( 1, 'upstream', full_upstream_name )
            log( 1, 'downstream', full_downstream_name )

            if not downstream_user or not downstream_repository:
                log.newline( count=3 )
                log( 1, "ERROR! Invalid downstream `%s`", downstream )

            try:
                fork_user = self.github_api.get_user( downstream_user )
                fork_repo = fork_user.get_repo( downstream_repository )

            except github.GithubException as error:
                self._register_error_reason( full_downstream_name, error )
                continue

            self.downstream_users.add( downstream_user )
            self.parsed_repositories.add( downstream_name )
            self.full_parsed_repositories[downstream_name] = fork_repo

            if not upstream_user or not upstream_repository:
                log( 1, "Skipping %s because the upstream is not defined...", section )
                self.skipped_repositories.append( "%s -> %s" % ( downstream_name, section ) )
                continue

            if not local_branch or not upstream_branch:
                log.newline( count=3 )
                log( 1, "ERROR! Invalid branches `%s`", branches )

            try:
                if self.is_dry_run:
                    fork_pullrequest = fork_repo.url

                else:
                    fork_pullrequest = fork_repo.create_pull(
                            "Update from {}".format( full_upstream_name ),
                            wrap_text( r"""
                                The upstream repository `{}` has some new changes that aren't in this fork.
                                So, here they are, ready to be merged!

                                This Pull Request was created programmatically by the
                                [githubpullrequests](https://github.com/evandrocoan/githubpullrequests).
                            """.format( full_upstream_name ), single_lines=True, ),
                            local_branch,
                            '{}:{}'.format( upstream_user, upstream_branch ),
                            False
                        )

                # Then play with your Github objects
                successful_resquests += 1
                log( 1, 'Successfully Created:', fork_pullrequest )

                self.repositories_results['Successfully Created'].append( full_downstream_name )
                if not self.is_dry_run: fork_pullrequest.add_to_labels( "backstroke" )

            except github.GithubException as error:
                self._register_error_reason( full_downstream_name, error )
                continue

    def _register_error_reason(self, full_downstream_name, error):
        error = "%s, %s" % (full_downstream_name, str( error ) )
        log( 1, 'Skipping... %s', error )

        for reason in self.skip_reasons:
            if reason in error:
                self.repositories_results[reason].append(full_downstream_name)
                break

        else:
            self.repositories_results['Unknown Reason'].append(error)

    def publish_report(self):
        log.newline()
        index = 0
        used_repositories = set()
        full_used_repositories = {}

        for user in self.downstream_users:
            fork_user = self.github_api.get_user( user )

            # For quick testing
            if self.maximum_repositories and index > self.maximum_repositories: break

            for repository in fork_user.get_repos():
                used_repositories.add( repository.full_name )

                if self.synced_repositories:
                    full_used_repositories[repository.full_name] = repository
                    index += 1

                    # For quick testing
                    if self.maximum_repositories and index > self.maximum_repositories: break

                    log( 1, 'fetching parent %s. %s', index, repository.full_name )
                    repository.parent

        log.newline()
        log.clean('Repositories results:')
        log.newline()

        def general_report(report_key):
            log.newline()
            log.clean('   ', report_key)
            values = self.repositories_results[report_key]

            if values:
                index = 0

                for item in values:
                    index += 1
                    log.clean('        %s. %s', index, item)

            else:
                log.clean('        No results.')

        index = 0
        log.clean('    Skipped due missing upstreams:')

        for skipped_repository in self.skipped_repositories:
            index += 1
            log.clean('        %s. %s', index, skipped_repository)

        report_first = 'No commits between'
        general_report(report_first)
        del self.repositories_results[report_first]

        if self.synced_repositories:
            index = 0
            log.newline()
            log.clean('    Repositories not Synchronized with Pull Requests:')

            for repository_name in used_repositories:
                repository = full_used_repositories[repository_name]

                if repository.parent:

                    if repository_name not in self.parsed_repositories:
                        index += 1
                        parent = repository.parent
                        log.clean( '        %s. %s@%s, upstream -> %s@%s', index, repository_name, repository.default_branch,
                                parent.full_name, parent.default_branch )

            if index == 0:
                log.clean('        No results.')

        log.newline()
        log.clean('    Possible Renamed Repositories:')

        index = 0
        renamed_repositories = self.parsed_repositories - used_repositories

        for repository_name in renamed_repositories:
            full_repository = self.full_parsed_repositories[repository_name]

            if full_repository.full_name != repository_name:
                index += 1
                log.clean( '        %s. %s, actual name -> %s', index, repository_name, full_repository.full_name )

        if index == 0: log.clean('        No results.')

        for report_key in self.repositories_results.keys():
            general_report(report_key)


def parser_branches(branches):
    matches = re.search( r'(.+)\-\>(.+),', branches )

    if matches:
        return matches.group(2), matches.group(1)

    return "", ""


def parse_github(url):
    matches = re.search( r'github\.com\/(.+)\/(.+)', url )

    if matches:
        user = matches.group(1)
        repository = matches.group(2)

        if repository.endswith('.git'): repository = repository[:-4]
        return user, repository

    return "", ""


@contextlib.contextmanager
def lock_context_manager():
    """
        https://stackoverflow.com/questions/12594148/skipping-execution-of-with-block
        https://stackoverflow.com/questions/27071524/python-context-manager-not-cleaning-up
        https://stackoverflow.com/questions/10447818/python-context-manager-conditionally-executing-body
        https://stackoverflow.com/questions/34775099/why-does-contextmanager-throws-a-runtime-error-generator-didnt-stop-after-thro
    """
    try:
        yield is_allowed_to_run()

    finally:
        free_mutex_lock()


def free_mutex_lock():
    global g_is_already_running
    g_is_already_running = False


def is_allowed_to_run():
    global g_is_already_running

    if g_is_already_running:
        log( 1, "You are already running a command. Wait until it finishes or restart Sublime Text" )
        return False

    g_is_already_running = True
    return True


def enable_github_issue_tracker(username):
    def add_star(index, repository_id):
        return wrap_text( """
            update%05d: updateRepository(input:{repositoryId:"%s", hasIssuesEnabled:true}) {
              repository {
                 nameWithOwner
              }
            }
        """ % ( index, repository_id ) )
    run_action_on_all_repositories(username, add_star)


def add_stars_on_github_repositories(username):
    def add_star(index, repository_id):
        return wrap_text( """
            update%05d: addStar(input:{starrableId:"%s"}) {
              clientMutationId
              starrable {
                viewerHasStarred
              }
            }
        """ % ( index, repository_id ) )
    run_action_on_all_repositories(username, add_star)


def watch_all_github_repositories(username):
    def add_star(index, repository_id):
        return wrap_text( """
            update%05d: updateSubscription(input:{subscribableId:"%s", state:SUBSCRIBED}) {
              clientMutationId
              subscribable {
                viewerSubscription
              }
            }
        """ % ( index, repository_id ) )
    run_action_on_all_repositories(username, add_star)


def run_action_on_all_repositories(username, action):
    """ We can only update up to 100 repositories at a time
    otherwise we get 502 bad gateway error from GitHub """
    queryvariables = {
        "user": username,
        "lastItem": None,
        "items": 100,
    }

    while True:
        repositories = get_all_user_repositories(queryvariables)

        # log('repositories', repositories)
        _enable_github_issue_tracker(repositories, action)

        if not queryvariables['hasNextPage']: break
        time.sleep(3)


def _enable_github_issue_tracker(repositories, action):
    graphqlquery = ""

    for index, repository in enumerate(repositories, start=1):
        repository_id = repository[1]
        graphqlquery += action(index, repository_id) + "\n"

    graphqlresults = run_graphql_query( headers, wrap_text( """
        mutation UpdateUserRepositories {
          %s
        }
        """ % graphqlquery )
    )
    log('graphqlresults', graphqlresults)


def get_all_user_repositories(queryvariables):
    repositories_found = []

    graphqlquery = wrap_text( """
        query ListUserRepositories($user: String!, $items: Int!, $lastItem: String) {
          repositoryOwner(login: $user) {
            repositories(first: $items, after: $lastItem, orderBy: {field: STARGAZERS, direction: DESC}, ownerAffiliations: [OWNER]) {
              pageInfo {
                hasNextPage
                endCursor
              }
              nodes {
                name
                id
                isArchived
              }
            }
          }
        }
    """ )

    graphqlresults = run_graphql_query( headers, graphqlquery, queryvariables )
    pageInfo = graphqlresults["data"]["repositoryOwner"]["repositories"]["pageInfo"]

    nodes = graphqlresults["data"]["repositoryOwner"]["repositories"]["nodes"]
    queryvariables['lastItem'] = pageInfo["endCursor"]
    queryvariables['hasNextPage'] = pageInfo["hasNextPage"]
    repositories_found.extend( (item['name'], item['id']) for item in nodes if not item['isArchived'] )

    # log(f"items {nodes} pageInfo {pageInfo}")
    log(f"items {len(repositories_found)} pageInfo {pageInfo}")

    return repositories_found


github_ratelimit_graphql = wrap_text( """
    rateLimit {
        limit
        cost
        remaining
        resetAt
    }
    viewer {
        login
    }
""" )


def log_ratelimit(headers):
    graphqlresults = run_graphql_query( headers, f"{{{github_ratelimit_graphql}}}" )
    resultdata = graphqlresults["data"]
    log(
        f"{resultdata['viewer']['login']}, "
        f"limit {resultdata['rateLimit']['remaining']}, "
        f"cost {resultdata['rateLimit']['cost']}, "
        f"{resultdata['rateLimit']['remaining']}, "
        f"{resultdata['rateLimit']['resetAt']}, "
    )


# A simple function to use requests.post to make the API call. Note the json= section.
# https://developer.github.com/v4/explorer/
def run_graphql_query(headers, graphqlquery, queryvariables={}, graphql_url="https://api.github.com/graphql"):
    """ headers { "Authorization": f"Bearer {github_token}" } """
    # https://github.com/evandrocoan/GithubRepositoryResearcher
    # https://gist.github.com/gbaman/b3137e18c739e0cf98539bf4ec4366ad
    request = requests.post( graphql_url, json={'query': graphqlquery, 'variables': queryvariables}, headers=headers )
    fix_line = lambda line: str(line).replace('\\n', '\n')

    if request.status_code == 200:
        result = request.json()

        if "data" not in result or "errors" in result:
            raise Exception( wrap_text( f"""
                There were errors while processing the query!

                graphqlquery:
                {fix_line(graphqlquery)}

                queryvariables:
                {fix_line(queryvariables)}

                errors:
                {json.dumps( result, indent=2, sort_keys=True )}
            """ ) )

    else:
        raise Exception( wrap_text( f"""
            Query failed to run by returning code of {request.status_code}.

            graphqlquery:
            {fix_line(graphqlquery)}

            queryvariables:
            {fix_line(queryvariables)}
        """ ) )

    return result


if __name__ == "__main__":
    main()
