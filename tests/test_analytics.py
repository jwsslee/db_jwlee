import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
import numpy as np
from analytics import performance,align_prices,indicators,validate_notebook,evaluate_alert
from data import KIS,APIError,service_error,http
from unittest.mock import patch
from urllib.error import HTTPError
import io,json,time

class AnalyticsTests(unittest.TestCase):
    def test_return_drawdown(self):
        result=performance([100,120,90,110])
        self.assertAlmostEqual(result['수익률(%)'],10)
        self.assertAlmostEqual(result['최대낙폭(%)'],-25)
    def test_common_dates_not_forward_filled(self):
        a=pd.DataFrame({'date':pd.to_datetime(['2026-01-01','2026-01-02','2026-01-03']),'close':[100,110,120]})
        b=pd.DataFrame({'date':pd.to_datetime(['2026-01-02','2026-01-03']),'close':[50,55]})
        x=align_prices({'a':a,'b':b},'2026-01-01','2026-01-03')
        self.assertEqual(len(x),2);self.assertEqual(x.iloc[0]['a'],110)
    def test_flat_rsi_and_insufficient_history(self):
        d=pd.DataFrame({'date':pd.date_range('2026-01-01',periods=30),'close':[100.]*30})
        self.assertEqual(indicators(d).RSI.iloc[-1],50)
        self.assertTrue(np.isnan(performance([100])['수익률(%)']))
    def test_missing_alert_does_not_trigger(self):
        self.assertEqual(evaluate_alert(np.nan,'이하',100),'데이터 없음')
        self.assertEqual(evaluate_alert(100,'이상',100),'조건 충족')
    def test_notebook_rejects_bad_input(self):
        with self.assertRaises(ValueError):validate_notebook({'version':1,'notes':[{'wrong':'x'}]})
    def test_error_response_hides_message(self):
        body=json.dumps({'msg_cd':'EGW00201','msg1':'private-account-info'}).encode()
        with patch('data.urlopen',side_effect=HTTPError('https://example.test',500,'error',{},io.BytesIO(body))):
            with self.assertRaises(APIError) as cm:http('https://example.test')
        self.assertEqual(cm.exception.code,'EGW00201')
        self.assertNotIn('private-account',str(cm.exception))
    def test_read_retries_bounded(self):
        k=KIS('test','test');k.token='test';k.expires=time.time()+3600
        with patch('data.http',side_effect=service_error(500,{})) as mock,patch('data.time.sleep'):
            with self.assertRaises(APIError):k.get('/test','test',{})
            self.assertEqual(mock.call_count,3)
    def test_financial_annual_mapping(self):
        k=KIS('test','test');calls=[]
        def get(endpoint,tr,params,continuation):
            calls.append(params)
            return {'output':[{'stac_yymm':'202512','sale_account':'100','bsop_prti':'20','roe_val':'12.4'}]},{}
        k.get=get
        result=k.financials('005930')
        self.assertTrue(all(p['FID_DIV_CLS_CODE']=='0' for p in calls))
        self.assertEqual(result['income-statement'].iloc[0].revenue,100)
        self.assertEqual(result['financial-ratio'].iloc[0].roe,12.4)
        self.assertTrue(pd.isna(result['financial-ratio'].iloc[0].debt_ratio))
    def test_balance_cursor_error_not_partial_success(self):
        k=KIS('test','test');k.get=lambda *args:({'output1':[],'output2':[]},{'tr_cont':'F'})
        with self.assertRaises(APIError):k.balance('12345678','01')

if __name__=='__main__':unittest.main()
