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
    args=parser.parse_args(argv)
    if args.command=='build': result=runtime.build_environment(args.root,args.wheelhouse)
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
