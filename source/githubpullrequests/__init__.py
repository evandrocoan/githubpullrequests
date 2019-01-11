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

import github
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
from debug_tools.estimated_time_left import sequence_timer
from debug_tools.estimated_time_left import progress_info

PACKAGE_ROOT_DIRECTORY = os.path.dirname( os.path.realpath( __file__ ) )
CHANNEL_SESSION_FILE = os.path.join( PACKAGE_ROOT_DIRECTORY, "last_session.json" )

MAXIMUM_WORSPACES_ENTRIES = 100

g_is_already_running = False
log = getLogger( 127, __name__ )


def main():
    github_token = os.environ.get( 'GITHUBPULLREQUESTS_TOKEN', "" )
    gitmodules_files = []
    synced_repositories = False
    maximum_repositories = 0

    # https://stackoverflow.com/questions/6382804/how-to-use-getopt-optarg-in-python-how-to-shift
    argumentParser = argparse.ArgumentParser( description='Create Pull Requests, using GitHub API and a list of repositories' )

    argumentParser.add_argument( "-f", "--file", action="append",
            help="The file with the repositories informations" )

    argumentParser.add_argument( "-t", "--token", action="store",
            help="GitHub token with `public_repos` access" )

    argumentParser.add_argument( "-mr", "--maximum-repositories", action="store", type=int,
            help="The maximum count of repositories/requests to process per file." )

    argumentParser.add_argument( "-c", "--cancel-operation", action="store_true",
            help="If there is some batch operation running, cancel it as soons as possible." )

    argumentParser.add_argument( "-s", "--synced-repositories", action="store_true",
            help="Reports which repositories not Synchronized with Pull Requests. "
            "This also resets/skips any last session saved due old throw/raised exceptions, "
            "because to compute correctly the repositories list, it is required to know all "
            "available repositories." )

    argumentsNamespace = argumentParser.parse_args()
    # log( 1, argumentsNamespace )

    if argumentsNamespace.cancel_operation:
        free_mutex_lock()
        return

    if argumentsNamespace.token:
        github_token = argumentsNamespace.token

    if argumentsNamespace.synced_repositories:
        synced_repositories = argumentsNamespace.synced_repositories

    if argumentsNamespace.maximum_repositories:
        maximum_repositories = argumentsNamespace.maximum_repositories

    if argumentsNamespace.file:
        gitmodules_files = argumentsNamespace.file

    else:
        log.clean( "Error: Missing required command line argument `-f/--file`" )
        argumentParser.print_help()
        return

    pull_requester = PullRequester( github_token, maximum_repositories, synced_repositories )
    pull_requester.parse_gitmodules( gitmodules_files )
    pull_requester.publish_report()


class PullRequester(object):

    def __init__(self, github_token, maximum_repositories=0, synced_repositories=False):
        super(PullRequester, self).__init__()

        if os.path.exists( github_token ):
            with open( github_token, 'r', ) as input_file:
                github_token = input_file.read()

        if synced_repositories:
            self.lastSection = OrderedDict()

        else:
            try:
                with open( CHANNEL_SESSION_FILE, 'r' ) as data_file:
                    self.lastSection = json.load( data_file, object_pairs_hook=OrderedDict )

            except( IOError, ValueError ):
                self.lastSection = OrderedDict()

        self.github_token = github_token.strip()
        self.maximum_repositories = maximum_repositories
        self.synced_repositories = synced_repositories

        self.last_module_file = None
        self.request_index = 0
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

            if not upstream_user or not upstream_repository:
                log( 1, "Skipping %s because the upstream is not defined...", section )
                continue

            branches = get_section_option( section, "branches", config_parser )
            local_branch, upstream_branch = parser_branches( branches )

            log( 1, branches )
            log( 1, 'upstream', upstream )
            log( 1, 'downstream', downstream )

            if not local_branch or not upstream_branch:
                log.newline( count=3 )
                log( 1, "ERROR! Invalid branches `%s`", branches )

            if not downstream_user or not downstream_repository:
                log.newline( count=3 )
                log( 1, "ERROR! Invalid downstream `%s`", downstream )

            fork_user = self.github_api.get_user( downstream_user )
            fork_repo = fork_user.get_repo( downstream_repository )
            full_upstream_name = "{}/{}@{}".format( upstream_user, upstream_repository, upstream_branch )

            downstream_name = "{}/{}".format( downstream_user, downstream_repository )
            full_downstream_name = "{} @ {}".format( downstream_name, section )
            self.downstream_users.add( downstream_user )
            self.parsed_repositories.add( downstream_name )

            try:
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

                self.repositories_results['Successfully Created'].append(full_downstream_name)
                fork_pullrequest.add_to_labels( "backstroke" )

            except github.GithubException as error:
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
        log.clean('Repositories results:')

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

        report_first = 'No commits between'
        general_report(report_first)
        del self.repositories_results[report_first]

        index = 0
        used_repositories = set()

        if self.synced_repositories:
            log.newline()
            log.clean('    Repositories not Synchronized with Pull Requests:')

        for user in self.downstream_users:
            fork_user = self.github_api.get_user( user )

            for repo in fork_user.get_repos():
                used_repositories.add( repo.full_name )

                if self.synced_repositories and repo.parent:

                    if repo.full_name not in self.parsed_repositories:
                        index += 1
                        log.clean( '        %s. %s', index, repo.full_name )

                        # For quick testing
                        if self.maximum_repositories and index > self.maximum_repositories:
                            break

        if self.synced_repositories:
            if index == 0: log.clean('        No results.')

        log.newline()
        log.clean('    Renamed Repositories:')

        index = 0
        renamed_repositories = self.parsed_repositories - used_repositories

        for repository in renamed_repositories:
            index += 1
            log.clean( '        %s. %s', index, repository )

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
        return matches.group(1), matches.group(2)

    return "", ""


def get_section_option(section, option, configSettings):

    if configSettings.has_option( section, option ):
        return configSettings.get( section, option )

    return ""


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


if __name__ == "__main__":
    main()
