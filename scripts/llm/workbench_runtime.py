"""Isolated runtime operator; no installation, production source or arbitrary command."""
import sys

# A fresh entry must not import ignored timestamp-valid source-tree bytecode.
# governance-mutation: RUNTIME_ENTRY_BYTECODE
sys.pycache_prefix = "/dev/null"
sys.dont_write_bytecode = True
import importlib.machinery


class _SourceOnlyImports:
    def find_spec(self, fullname, path=None, target=None):
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        # governance-mutation: RUNTIME_ENTRY_SOURCELESS
        if spec is not None and isinstance(spec.loader, importlib.machinery.SourcelessFileLoader):
            raise ImportError('SOURCELESS_MODULE_REFUSED')
        return None


sys.meta_path.insert(0, _SourceOnlyImports())

import argparse
import json
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
import workbench_runtime_env as runtime
import workbench_runtime_service as service


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    build=commands.add_parser('build'); build.add_argument('--root',type=Path,required=True); build.add_argument('--wheelhouse',type=Path,required=True)
    prepare=commands.add_parser('prepare')
    prepare.add_argument('--root',type=Path,required=True); prepare.add_argument('--code',type=Path,required=True)
    prepare.add_argument('--environment',type=Path,required=True); prepare.add_argument('--environment-pin',required=True)
    prepare.add_argument('--port',type=int,required=True)
    for name in ('verify','serve','child'):
        sub=commands.add_parser(name); sub.add_argument('--profile',type=Path,required=True); sub.add_argument('--pin',required=True)
        if name=='serve': sub.add_argument('--seconds',type=int,default=300)
        if name=='child': sub.add_argument('--parent',type=int,required=True)
    recovery=commands.add_parser('recovery-prepare')
    recovery.add_argument('--root',type=Path,required=True)
    recovery.add_argument('--backup',type=Path,required=True)
    recovery.add_argument('--backup-pin',required=True)
    recovery.add_argument('--code',type=Path,required=True)
    recovery.add_argument('--environment',type=Path,required=True)
    recovery.add_argument('--environment-pin',required=True)
    recovery.add_argument('--port',type=int,required=True)
    recovery.add_argument('--source',type=Path)
    recovery.add_argument('--library',type=Path)
    recovery.add_argument('--library-pin')
    recovery.add_argument('--research-cards',action='store_true',help='Explicit synthetic recovery-v2 opt-in for registered card tasks')
    for name in ('recovery-verify','recovery-serve','recovery-child'):
        sub=commands.add_parser(name); sub.add_argument('--profile',type=Path,required=True); sub.add_argument('--pin',required=True)
        if name=='recovery-serve': sub.add_argument('--seconds',type=int,default=300)
        if name=='recovery-child': sub.add_argument('--parent',type=int,required=True)
    args=parser.parse_args(argv)
    if args.command.startswith('recovery-'):
        import workbench_recovery
        if args.command=='recovery-prepare':
            result=workbench_recovery.prepare(args.root,args.backup,args.backup_pin,args.code,args.environment,
                args.environment_pin,args.port,source_root=args.source,library_root=args.library,library_hash=args.library_pin,
                cards_enabled=args.research_cards)
        elif args.command=='recovery-verify':
            value=workbench_recovery.verify(args.profile,args.pin)
            result={'status':'PINNED_ISOLATED_RECOVERY_VALID','code_sha':value['code_identity']['code_sha'],
                    'physical_host_reboot':'NOT_ATTESTED','production_authority':False}
        elif args.command=='recovery-serve': result=workbench_recovery.serve(args.profile,args.pin,args.seconds)
        else: return workbench_recovery.run_child(args.profile,args.pin,args.parent)
    elif args.command=='build': result=runtime.build_environment(args.root,args.wheelhouse)
    elif args.command=='prepare': result=service.prepare_profile(args.root,args.code,args.environment,args.environment_pin,args.port)
    elif args.command=='verify':
        value=service.verify_profile(args.profile,args.pin)
        result={'status':'PINNED_ISOLATED_PROFILE_VALID','code_sha':value['code_identity']['code_sha'],'production_authority':False}
    elif args.command=='serve': result=service.serve_profile(args.profile,args.pin,args.seconds)
    else: return service.run_child(args.profile,args.pin,args.parent)
    print(json.dumps(result,sort_keys=True)); return 2 if result.get('status')=='FAILED' else 0


if __name__=='__main__':
    try: raise SystemExit(main())
    except (ValueError,OSError,KeyError,TypeError,RuntimeError) as exc:
        print('ISOLATED_RUNTIME_REFUSED: '+type(exc).__name__+': '+str(exc),file=sys.stderr)
        raise SystemExit(2)
