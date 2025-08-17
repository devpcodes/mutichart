def get_main_contracts(api):
    # 所有期貨合約
    futures = api.Contracts.Futures

    # 過濾 TXF、MXF
    txf_contracts = sorted([c.code for c in futures if c.code.startswith("TXF")])
    mxf_contracts = sorted([c.code for c in futures if c.code.startswith("MXF")])

    # 取最近月份
    main_txf = txf_contracts[0] if txf_contracts else None
    main_mxf = mxf_contracts[0] if mxf_contracts else None

    return main_txf, main_mxf
