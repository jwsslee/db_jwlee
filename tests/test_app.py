import unittest,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from streamlit.testing.v1 import AppTest
import data

class DashboardTests(unittest.TestCase):
    def app(self):return AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=40)
    def test_all_demo_pages_and_note(self):
        at=self.app().run();self.assertFalse(at.exception)
        for page in ['종목 리서치','종목 비교','실적과 가치','조건 검색','내 포트폴리오','알림과 투자 노트','연결 안내']:
            next(x for x in at.radio if x.label=='리서치 메뉴').set_value(page).run()
            self.assertFalse(at.exception,page)
        next(x for x in at.radio if x.label=='리서치 메뉴').set_value('알림과 투자 노트').run()
        next(x for x in at.text_area if x.label=='투자 이유').set_value('성장률 점검')
        next(x for x in at.button if x.label=='노트 추가').click().run()
        self.assertFalse(at.exception);self.assertEqual(len(at.session_state['notes']),1)
    def test_api_failure_stays_warning(self):
        at=self.app();at.secrets={'KIS_APP_KEY':'test','KIS_APP_SECRET':'test'};at.run()
        with patch.object(data.KIS,'get',side_effect=data.APIError('TEST: simulated failure')):
            next(x for x in at.radio if x.label=='데이터 모드').set_value('API 연결').run()
            self.assertFalse(at.exception)
            self.assertTrue(any('simulated failure' in x.value for x in at.warning))
            next(x for x in at.radio if x.label=='리서치 메뉴').set_value('종목 리서치').run()
            self.assertFalse(at.exception)
    def test_account_not_requested_before_unlock(self):
        at=self.app();at.secrets={'KIS_APP_KEY':'test','KIS_APP_SECRET':'test','DASHBOARD_PASSWORD':'test-pass'};at.run()
        next(x for x in at.radio if x.label=='리서치 메뉴').set_value('내 포트폴리오').run()
        with patch.object(data.KIS,'balance') as mock:
            next(x for x in at.radio if x.label=='데이터 모드').set_value('API 연결').run()
            self.assertFalse(at.exception);mock.assert_not_called()
            next(x for x in at.text_input if x.label=='잔고 조회 비밀번호').set_value('wrong').run()
            mock.assert_not_called()

if __name__=='__main__':unittest.main()
