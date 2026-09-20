"""Read-only KRX/KIS adapters. Never logs secrets or raw HTTP errors."""
from __future__ import annotations
import json, time, threading, re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import numpy as np
import pandas as pd

KST = ZoneInfo('Asia/Seoul')
class APIError(Exception):
    def __init__(self, message, status=None, code=''):
        super().__init__(message)
        self.status, self.code = status, code


def service_error(status=None, body=None):
    # Only a strict service-code format is exposed. Never echo msg1 or bodies.
    raw = str(body.get('msg_cd', '')) if isinstance(body, dict) else ''
    code = raw if re.fullmatch(r'[A-Z]{3,8}[0-9]{3,8}', raw) else ''
    label = (f'HTTP {status}' if status else '한국투자증권 오류') + (f' · {code}' if code else '')
    if code == 'EGW00201' or status == 429:
        hint = '호출 한도 초과입니다. 같은 키를 사용하는 다른 앱을 잠시 중지하고 다시 조회하세요.'
    elif status in (401, 403):
        hint = '인증 또는 접근 권한 오류입니다. 키와 실전/모의 환경을 확인하세요.'
    elif status and status >= 500:
        hint = '서버가 요청을 처리하지 못했습니다. 잠시 후 다시 조회하고, 반복되면 이 오류 코드를 확인하세요.'
    else:
        hint = '요청을 처리하지 못했습니다. 해당 오류 코드의 권한·환경·입력 조건을 확인하세요.'
    return APIError(f'{label}: {hint}', status, code)


def now():
    return datetime.now(KST)

def number(value):
    try:
        return float(str(value).replace(',', ''))
    except (ValueError, TypeError):
        return float('nan')

def http(url, headers=None, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = Request(url, data=data, headers=headers or {})
    try:
        with urlopen(req, timeout=15) as res:
            return json.load(res), dict(res.headers)
    except HTTPError as e:
        try:
            body = json.loads(e.read(16384).decode('utf-8'))
        except (ValueError, OSError):
            body = None
        raise service_error(e.code, body) from None
    except (URLError, TimeoutError, ValueError, OSError):
        raise APIError('응답을 받지 못했습니다. 네트워크 또는 서비스 상태를 확인하세요.') from None

class KIS:
    def __init__(self, key, secret, env='prod'):
        self.key, self.secret = key, secret
        self.env = env
        self.base = 'https://openapi.koreainvestment.com:9443' if env == 'prod' else 'https://openapivts.koreainvestment.com:29443'
        self.token, self.expires, self.last_call = '', 0, 0
        self.lock = threading.RLock()
        self.last_auth_attempt = 0

    def get(self, endpoint, tr, params, continuation=''):
        from urllib.parse import urlencode
        with self.lock:
            if time.time() >= self.expires:
                if time.time() - self.last_auth_attempt < 65:
                    raise APIError('토큰 발급 대기 중입니다. 약 1분 후 다시 조회하세요.')
                self.last_auth_attempt = time.time()
                obj, _ = http(self.base + '/oauth2/tokenP', {'Content-Type':'application/json'},
                              {'grant_type':'client_credentials','appkey':self.key,'appsecret':self.secret})
                if not obj.get('access_token'):
                    raise APIError('접근 토큰 발급 실패: App Key, App Secret, 실전/모의 환경을 확인하세요.')
                self.token = obj['access_token']
                self.expires = time.time() + max(1, int(obj.get('expires_in', 86400)) - 120)
            # GET requests only: bounded retries for throttling and transient failures.
            for attempt in range(3):
                time.sleep(max(0, 1.1 - (time.monotonic() - self.last_call)))
                self.last_call = time.monotonic()
                try:
                    obj, headers = http(self.base + endpoint + '?' + urlencode(params),
                        {'authorization':f'Bearer {self.token}', 'appkey':self.key, 'appsecret':self.secret,
                         'tr_id':tr, 'custtype':'P', 'tr_cont':continuation, 'Content-Type':'application/json'})
                    if str(obj.get('rt_cd')) != '0':
                        raise service_error(body=obj)
                    return obj, {k.lower():v for k,v in headers.items()}
                except APIError as exc:
                    retryable = (exc.code == 'EGW00201' or exc.status == 429 or
                                 (not exc.code and exc.status in (500, 502, 503, 504)))
                    if not retryable or attempt == 2:
                        raise APIError(f'{tr} · {exc}', exc.status, exc.code) from None
                    time.sleep(2 ** (attempt + 1))

    def quote(self, code):
        o, _ = self.get('/uapi/domestic-stock/v1/quotations/inquire-price', 'FHKST01010100',
                        {'FID_COND_MRKT_DIV_CODE':'J','FID_INPUT_ISCD':code})
        r = o['output']
        return dict(code=code, price=number(r.get('stck_prpr')), change=number(r.get('prdy_ctrt')),
                    volume=number(r.get('acml_vol')), value=number(r.get('acml_tr_pbmn')),
                    per=number(r.get('per')), pbr=number(r.get('pbr')), eps=number(r.get('eps')),
                    market_cap=number(r.get('hts_avls')), high52=number(r.get('w52_hgpr')), fetched=now())

    def index(self, code):
        o, _ = self.get('/uapi/domestic-stock/v1/quotations/inquire-index-price', 'FHPUP02100000',
                        {'FID_COND_MRKT_DIV_CODE':'U','FID_INPUT_ISCD':code})
        r = o['output']
        return dict(price=number(r.get('bstp_nmix_prpr')),change=number(r.get('bstp_nmix_prdy_ctrt')),fetched=now())

    def history(self, code, days=600):
        end, start = now().date(), now().date()-timedelta(days=days)
        rows = []
        for _ in range(12):
            o, _ = self.get('/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice', 'FHKST03010100',
                {'FID_COND_MRKT_DIV_CODE':'J','FID_INPUT_ISCD':code,'FID_INPUT_DATE_1':start.strftime('%Y%m%d'),
                 'FID_INPUT_DATE_2':end.strftime('%Y%m%d'),'FID_PERIOD_DIV_CODE':'D','FID_ORG_ADJ_PRC':'0'})
            batch = [r for r in o.get('output2',[]) if r.get('stck_bsop_date')]
            if not batch: break
            rows.extend(batch)
            earliest = min(datetime.strptime(r['stck_bsop_date'],'%Y%m%d').date() for r in batch)
            if earliest <= start: break
            new_end = earliest - timedelta(days=1)
            if new_end >= end: raise APIError('가격 데이터 연속 조회가 진행되지 않습니다.')
            end = new_end
        if not rows: raise APIError('이 종목의 가격 이력이 없습니다.')
        df = pd.DataFrame(rows).rename(columns={'stck_bsop_date':'date','stck_oprc':'open',
            'stck_hgpr':'high','stck_lwpr':'low','stck_clpr':'close','acml_vol':'volume'})
        df['date'] = pd.to_datetime(df['date'], format='%Y%m%d', errors='coerce')
        for col in ['open','high','low','close','volume']: df[col] = df[col].map(number)
        return df[['date','open','high','low','close','volume']].dropna().drop_duplicates('date').sort_values('date')

    def flow(self, code):
        o, _ = self.get('/uapi/domestic-stock/v1/quotations/inquire-investor', 'FHKST01010900',
                        {'FID_COND_MRKT_DIV_CODE':'J','FID_INPUT_ISCD':code})
        df = pd.DataFrame(o.get('output',[]))
        if df.empty: raise APIError('수급 데이터가 없습니다.')
        df = df.rename(columns={'stck_bsop_date':'date','prsn_ntby_qty':'개인','frgn_ntby_qty':'외국인','orgn_ntby_qty':'기관'})
        df['date'] = pd.to_datetime(df['date'], format='%Y%m%d', errors='coerce')
        for col in ['개인','외국인','기관']: df[col] = df[col].map(number)
        return df[['date','개인','외국인','기관']].dropna(subset=['date']).drop_duplicates('date').sort_values('date')

    def benchmark(self, code, days=600):
        end, start = now().date(), now().date()-timedelta(days=days)
        rows = []
        for _ in range(15):
            obj, _ = self.get('/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice', 'FHKUP03500100',
                {'FID_COND_MRKT_DIV_CODE':'U','FID_INPUT_ISCD':code,
                 'FID_INPUT_DATE_1':start.strftime('%Y%m%d'),'FID_INPUT_DATE_2':end.strftime('%Y%m%d'),
                 'FID_PERIOD_DIV_CODE':'D'})
            batch = [r for r in obj.get('output2',[]) if r.get('stck_bsop_date')]
            if not batch: break
            rows.extend(batch)
            earliest = min(datetime.strptime(r['stck_bsop_date'],'%Y%m%d').date() for r in batch)
            if earliest <= start: break
            new_end = earliest-timedelta(days=1)
            if new_end >= end: raise APIError('지수 이력 연속 조회가 진행되지 않습니다.')
            end = new_end
        if not rows: raise APIError('지수 이력이 없습니다.')
        df = pd.DataFrame(rows)
        return pd.DataFrame({'date':pd.to_datetime(df['stck_bsop_date'],format='%Y%m%d',errors='coerce'),
            'close':df['bstp_nmix_prpr'].map(number)}).dropna().drop_duplicates('date').sort_values('date')

    def financials(self, code):
        # Annual statements avoid mistaking year-to-date quarterly data for one quarter.
        result = {}
        for kind,tr,fields in [
            ('income-statement','FHKST66430200',{'sale_account':'revenue','bsop_prti':'operating','thtr_ntin':'net_income'}),
            ('financial-ratio','FHKST66430300',{'grs':'revenue_growth','bsop_prfi_inrt':'operating_growth',
                'roe_val':'roe','lblt_rate':'debt_ratio','eps':'eps','bps':'bps'})]:
            rows, continuation, previous = [], '', None
            for _ in range(10):
                obj,hdr=self.get('/uapi/domestic-stock/v1/finance/'+kind,tr,
                    {'FID_DIV_CLS_CODE':'0','fid_cond_mrkt_div_code':'J','fid_input_iscd':code},continuation)
                batch=obj.get('output',[])
                if isinstance(batch,dict): batch=[batch]
                marker=json.dumps(batch,sort_keys=True)
                if marker==previous and hdr.get('tr_cont') in ('M','F'):
                    raise APIError('재무자료 연속 조회가 진행되지 않습니다.')
                previous=marker; rows.extend(batch)
                if hdr.get('tr_cont') not in ('M','F'): break
                continuation='N'
            else: raise APIError('재무자료 연속 조회 한도를 초과했습니다.')
            if not rows:
                result[kind]=pd.DataFrame();continue
            df=pd.DataFrame(rows)
            if 'stac_yymm' not in df: raise APIError('재무자료 결산 기준일이 없습니다.')
            out=pd.DataFrame({'period':df['stac_yymm'].astype(str)})
            for src,dst in fields.items():out[dst]=df[src].map(number) if src in df else np.nan
            result[kind]=out.drop_duplicates('period').sort_values('period')
        return result

    def balance(self, cano, product):
        params = dict(CANO=cano,ACNT_PRDT_CD=product,AFHR_FLPR_YN='N',OFL_YN='',INQR_DVSN='02',
            UNPR_DVSN='01',FUND_STTL_ICLD_YN='N',FNCG_AMT_AUTO_RDPT_YN='N',PRCS_DVSN='00',
            CTX_AREA_FK100='',CTX_AREA_NK100='')
        rows, summary, seen = [], {}, set()
        cont = ''
        for _ in range(100):
            obj, hdr = self.get('/uapi/domestic-stock/v1/trading/inquire-balance',
                'TTTC8434R' if self.env=='prod' else 'VTTC8434R',params,cont)
            rows.extend(obj.get('output1', []))
            if not summary and obj.get('output2'): summary = obj['output2'][0]
            if hdr.get('tr_cont') not in ('F','M'): break
            cursor = (obj.get('ctx_area_fk100',''),obj.get('ctx_area_nk100',''))
            if cursor in seen or not any(cursor): raise APIError('잔고 연속 조회가 중단되어 전체 잔고를 표시할 수 없습니다.')
            seen.add(cursor)
            params['CTX_AREA_FK100'], params['CTX_AREA_NK100'] = cursor
            cont = 'N'
        else: raise APIError('잔고 조회 페이지 한도를 초과했습니다.')
        table = pd.DataFrame([{'종목':r.get('prdt_name',r.get('pdno','')), '코드':r.get('pdno',''),
            '수량':number(r.get('hldg_qty')),'평균매입가':number(r.get('pchs_avg_pric')),
            '현재가':number(r.get('prpr')),'평가금액':number(r.get('evlu_amt')),
            '평가손익':number(r.get('evlu_pfls_amt')),'수익률(%)':number(r.get('evlu_pfls_rt'))} for r in rows])
        if not table.empty: table = table[table['수량'] > 0].drop_duplicates('코드')
        return table, summary, now()

def krx_market(key, market, date):
    from urllib.parse import urlencode
    name = 'stk_bydd_trd' if market=='KOSPI' else 'ksq_bydd_trd'
    obj, _ = http('https://data-dbg.krx.co.kr/svc/apis/sto/'+name+'?'+urlencode({'basDd':date}), {'AUTH_KEY':key})
    if 'OutBlock_1' not in obj: raise APIError('KRX 응답 오류: 인증키 및 해당 시장의 일별매매정보 이용 승인을 확인하세요.')
    df = pd.DataFrame(obj['OutBlock_1'])
    if df.empty: return df
    df = df.rename(columns={'ISU_CD':'코드','ISU_NM':'종목','TDD_CLSPRC':'종가','FLUC_RT':'등락률(%)',
        'ACC_TRDVAL':'거래대금','ACC_TRDVOL':'거래량'})
    for c in ['종가','등락률(%)','거래대금','거래량']: df[c] = df[c].map(number)
    return df[['코드','종목','종가','등락률(%)','거래대금','거래량']]

NAMES = {'005930':'삼성전자','000660':'SK하이닉스','035420':'NAVER','005380':'현대차','051910':'LG화학','035720':'카카오'}
def demo_history(code):
    rng = np.random.default_rng(int(code))
    dates = pd.bdate_range(end=now().date()-timedelta(days=1),periods=300)
    close = (70000 if code=='005930' else 120000)*np.exp(np.cumsum(rng.normal(.0008,.016,len(dates))))
    op = close*(1+rng.normal(0,.005,len(dates)))
    return pd.DataFrame({'date':dates,'open':op,'high':np.maximum(op,close)*(1+rng.uniform(.001,.012,len(dates))),
        'low':np.minimum(op,close)*(1-rng.uniform(.001,.012,len(dates))),'close':close.round(),
        'volume':rng.integers(3000000,18000000,len(dates))})
def demo_quote(code):
    d = demo_history(code)
    return dict(code=code,price=d.close.iloc[-1], change=(d.close.iloc[-1]/d.close.iloc[-2]-1)*100,
        volume=d.volume.iloc[-1],value=d.close.iloc[-1]*d.volume.iloc[-1],per=14.2+int(code)%7,
        pbr=1.25+(int(code)%5)/10,eps=5300,market_cap=4300000,high52=d.tail(252).high.max(),fetched=now())
def demo_flow(code):
    rng = np.random.default_rng(int(code)+1)
    d = demo_history(code).tail(30)[['date']].copy()
    d['외국인'] = rng.integers(-700000,1400000,len(d)); d['기관'] = rng.integers(-500000,800000,len(d))
    d['개인'] = -d['외국인']-d['기관']
    return d




def demo_financials(code):
    r=np.random.default_rng(int(code)); years=[str(now().year-i)+'12' for i in range(5,0,-1)]
    sales=np.array([180,215,230,210,265])*1e6
    income=pd.DataFrame({'period':years,'revenue':sales,'operating':sales*np.array([.12,.16,.11,.09,.18]),'net_income':sales*.09})
    ratios=pd.DataFrame({'period':years,'revenue_growth':[8,19.4,7,-8.7,26.2],
        'operating_growth':[12,59,-26.5,-25,152],'roe':r.uniform(7,18,5),
        'debt_ratio':r.uniform(25,50,5),'eps':r.uniform(3000,6000,5),'bps':r.uniform(40000,60000,5)})
    return {'income-statement':income,'financial-ratio':ratios}
