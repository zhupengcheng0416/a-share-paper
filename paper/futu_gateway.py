import os


class FutuGateway:
    """Read-only connectivity preflight. Execution is blocked until lifecycle tests.
    Every account-sensitive read explicitly supplies SIMULATE and the account ID.
    """
    def __init__(self):
        import futu
        self.futu=futu
        self.acc_id=int(os.environ['FUTU_SIM_ACC_ID'])
        if self.acc_id <= 0:
            raise ValueError('explicit simulation account required')
        self.quote=futu.OpenQuoteContext(host='127.0.0.1',port=11111)
        self.trade=futu.OpenSecTradeContext(filter_trdmarket=futu.TrdMarket.CN,host='127.0.0.1',port=11111,security_firm=futu.SecurityFirm.FUTUSECURITIES)
    def _checked(self,result):
        ret,data=result
        if ret != self.futu.RET_OK:
            raise RuntimeError(str(data))
        return data
    def verify_account(self):
        accounts=self._checked(self.trade.get_acc_list())
        rows=accounts[accounts['acc_id'].astype(str)==str(self.acc_id)]
        if len(rows)!=1 or str(rows.iloc[0]['trd_env'])!='SIMULATE':
            raise RuntimeError('requested account is not SIMULATE')
        return rows.to_dict('records')
    def status(self):
        self.verify_account()
        args={'trd_env':self.futu.TrdEnv.SIMULATE,'acc_id':self.acc_id}
        return {'accounts':self.verify_account(),'assets':self._checked(self.trade.accinfo_query(**args)).to_dict('records'),'positions':self._checked(self.trade.position_list_query(**args)).to_dict('records'),'orders':self._checked(self.trade.order_list_query(**args)).to_dict('records')}
    def submit(self,*args,**kwargs):
        raise RuntimeError('Execution unavailable: data, risk parameters, EXIT lifecycle and cloud preflight pending')
    def close(self):
        self.quote.close()
        self.trade.close()
