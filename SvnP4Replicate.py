#!/usr/bin/env python

import os
import sys
import tempfile

from lib.buildlogger import getLogger, set_logging_color_format
from lib.buildcommon import (working_in_dir, remove_dir_contents)
from lib.scmrepargs import get_arguments
from lib.p4server import P4Server
from lib.PerforceReplicate import P4Transfer
from lib.SvnPython import SvnPython 
from P4P4Replicate import (create_p4_workspace,
                           delete_p4_workspace,)
from lib.SubversionToPerforce import SubversionToPerforce

logger = getLogger(__name__)
logger.setLevel('DEBUG')


def create_Svn2P4_cfg_file(src_cfg, dst_cfg):
    '''create cfg file for svn2p4 replicating script

    A temporary file is generated by this function.

    @param src_cfg dict instance for svn cfgs
    @param dst_cfg dict instance for p4 cfgs
    '''
    svn_cfg_item = ['svn_client_root', 'svn_repo_label',
                    'svn_project_dir', 'svn_repo_url', 'svn_user',
                    'svn_passwd', 'counter', 'endchange', 'svn_view_mapping',]
    p4_cfg_item = ['p4client', 'p4port', 'p4user', 'p4passwd']

    src_cfg_str = '\n'.join(['%s=%s' % (k, v)
                             for k, v in src_cfg.items()
                             if k in svn_cfg_item and v is not None])
    tgt_cfg_str = '\n'.join(['%s=%s' %(k, v)
                             for k, v in dst_cfg.items()
                             if k in p4_cfg_item and v is not None])
    src_content = '[source]\n' + src_cfg_str
    tgt_content = '[target]\n' + tgt_cfg_str
    gen_content = '[general]\n'

    cfg_content = '\n'.join([src_content, tgt_content, gen_content])

    cfg_fd, cfg_path = tempfile.mkstemp(suffix='.cfg', text=True)
    os.write(cfg_fd, cfg_content)
    os.close(cfg_fd)

    return cfg_path


def replicate(args):
    '''Create temporary workspace and cfg file for svn2p4 replicating
    script and call it to replicate.
    '''
    if (not hasattr(args, 'source_workspace_view_cfgfile') or
        not args.source_workspace_view_cfgfile):
        if (hasattr(args, 'source_replicate_dir_cfgfile') and
            args.source_replicate_dir_cfgfile):
            args.source_workspace_view_cfgfile = args.source_replicate_dir_cfgfile
        else:
            logger.error('cfg file for source dir to replicate required')
            sys.exit(1)

    src_cfg = {'svn_repo_url': args.source_port,
               'svn_user': args.source_user,
               'svn_passwd': args.source_passwd,
               'svn_project_dir': None,
               'counter': args.source_counter,
               'endchange': args.source_last_changeset,
               'ws_root': args.workspace_root,
               'mappingcfg': args.source_workspace_view_cfgfile,
               'svn_repo_label': args.source_port,
               'svn_client_root': args.workspace_root,}

    dst_cfg = {'p4port': args.target_port,
               'p4user': args.target_user,
               'p4passwd': args.target_passwd,
               'ws_root': args.workspace_root,
               'mappingcfg': args.target_workspace_view_cfgfile, }

    # create target p4 workspace
    dst_p4 = P4Server(dst_cfg['p4port'], dst_cfg['p4user'],
                      dst_cfg['p4passwd'])
    create_p4_workspace(dst_p4, dst_cfg)
    dst_cfg['p4client'] = dst_p4.client

    # update project dir
    svn_replicate_dir = None
    with open(src_cfg['mappingcfg'], 'rt') as f:
        svn_replicate_view_mapping = list(f)

    svn_replicate_view_mapping.append('-/reptest_rename/src')
    svn_replicate_dir = svn_replicate_view_mapping[0].strip()
    src_cfg['svn_project_dir'] = svn_replicate_dir
    src_cfg['svn_view_mapping'] = src_cfg['mappingcfg']

    dry_run = hasattr(args, 'dry_run') and args.dry_run
    if not dry_run:
        ws_root = src_cfg['ws_root']
        has_existing_wc = os.path.isdir(os.path.join(ws_root, '.svn'))

        # checkout working copy
        svn = SvnPython(src_cfg['svn_repo_url'], src_cfg['svn_user'],
                        src_cfg['svn_passwd'], src_cfg['ws_root'])
        if not has_existing_wc:
            counter = int(src_cfg['counter'])
            if counter == 0:
                counter = -1
            svn.checkout_working_copy(src_cfg['svn_project_dir'],
                                      counter,
                                      depth='empty')
        else:
            # if it's already a working copy, we are probably resuming
            # a previously failed replication. Run 'svn cleanup' here
            # to release any locks.
            svn.run_cleanup(ws_root)
        svn.client = None

    try:
        # create cfg file
        svn2p4RepCfgFile = create_Svn2P4_cfg_file(src_cfg, dst_cfg)

        # make a new argv for svn2p4 script
        sys.argv = [__name__, '-c', svn2p4RepCfgFile]
        if args.maximum:
            sys.argv.extend(['-m', str(args.maximum)])

        if dry_run:
            sys.argv.append('--dry-run')

        if args.verbose:
            sys.argv.extend(['--verbose', args.verbose])

        if (hasattr(args, 'prefix_description_with_replication_info')
            and args.prefix_description_with_replication_info):
            sys.argv.append('--prefix-description-with-replication-info')

        if args.replicate_user_and_timestamp:
            sys.argv.extend(['--replicate-user-and-timestamp'])

        if hasattr(args, 'svn_ignore_externals'):
            sys.argv.extend(['--svn-ignore-externals'])

        # let's go
        ret = SubversionToPerforce()
    except Exception, e:
        logger.error(e)
        raise
    else:
        remove_dir_contents(src_cfg['ws_root'])
    finally:
        os.remove(svn2p4RepCfgFile)
        delete_p4_workspace(dst_p4)

    return ret

if __name__ == '__main__':
    args = get_arguments('SVN', 'P4')
    logger.setLevel(args.verbose)

    replicate(args)