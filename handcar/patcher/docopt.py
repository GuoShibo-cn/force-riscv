def docopt(doc):
    import sys
    argv = sys.argv[1:]
    return {
        'generate': 'generate' in argv,
        'patch': 'patch' in argv,
        '--clean': '--clean' in argv,
        '--verbose': '--verbose' in argv,
    }
