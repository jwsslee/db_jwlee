"""Price analytics: aligned dates, missing values preserved, no trading advice."""
import numpy as np
import pandas as pd

def indicators(frame):
    d=frame.sort_values('date').copy()
    for n in [20,60,120]: d[f'MA{n}']=d.close.rolling(n).mean()
    delta=d.close.diff();gain=delta.clip(lower=0).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    loss=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    rs=gain/loss.replace(0,np.nan)
    d['RSI']=100-100/(1+rs)
    d.loc[(loss==0)&(gain>0),'RSI']=100
    d.loc[(loss==0)&(gain==0),'RSI']=50
    d['MACD']=d.close.ewm(span=12,adjust=False).mean()-d.close.ewm(span=26,adjust=False).mean()
    d['Signal']=d.MACD.ewm(span=9,adjust=False).mean()
    d['upper']=d.MA20+2*d.close.rolling(20).std();d['lower']=d.MA20-2*d.close.rolling(20).std()
    return d

def performance(prices):
    s=pd.Series(prices).dropna();s=s[s>0]
    if len(s)<2:return {'수익률(%)':np.nan,'연환산 변동성(%)':np.nan,'최대낙폭(%)':np.nan}
    return {'수익률(%)':(s.iloc[-1]/s.iloc[0]-1)*100,
        '연환산 변동성(%)':s.pct_change(fill_method=None).dropna().std(ddof=1)*np.sqrt(252)*100,
        '최대낙폭(%)':(s/s.cummax()-1).min()*100}

def align_prices(frames,start,end):
    series=[]
    for name,frame in frames.items():
        d=frame.drop_duplicates('date').set_index('date')['close'].sort_index()
        series.append(d.rename(name))
    if not series:return pd.DataFrame()
    combined=pd.concat(series,axis=1,join='inner').loc[pd.Timestamp(start):pd.Timestamp(end)]
    return combined.where(combined>0).dropna()

def validate_notebook(obj):
    if not isinstance(obj,dict) or obj.get('version')!=1:raise ValueError('지원하지 않는 메모 파일입니다.')
    rows=obj.get('notes',[])
    if not isinstance(rows,list) or len(rows)>1000:raise ValueError('메모는 최대 1,000개입니다.')
    fields=['날짜','종목','매수 이유','점검 조건','다음 점검일']
    result=[]
    for row in rows:
        if not isinstance(row,dict) or any(k not in row for k in fields):raise ValueError('메모 형식을 확인하세요.')
        if any(not isinstance(row[k],str) or len(row[k])>5000 for k in fields):raise ValueError('메모 값이 올바르지 않습니다.')
        result.append({k:row[k] for k in fields})
    return result

def evaluate_alert(value,operator,threshold):
    if pd.isna(value):return '데이터 없음'
    return '조건 충족' if (value>=threshold if operator=='이상' else value<=threshold) else '대기'
