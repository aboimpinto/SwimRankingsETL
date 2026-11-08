import sys, unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import nrt_ssh_session as session
from nrt_verifier_bundle import verifier_source

class OwnedSshSession(unittest.TestCase):
 def test_session_is_closed_even_when_operation_fails(self):
  child=MagicMock();child.poll.return_value=None
  with patch.object(session.subprocess,'Popen',return_value=child),patch.object(session.subprocess,'run') as run,patch.object(Path,'exists',return_value=True):
   with self.assertRaisesRegex(RuntimeError,'operation failed'):
    with session.ssh_session('aws-fixture') as socket:
     self.assertTrue(Path(socket).is_absolute());raise RuntimeError('operation failed')
   self.assertEqual([c.args[0][-2] for c in run.call_args_list],['check','exit']);child.wait.assert_called_once();child.stderr.close.assert_called_once()
 def test_startup_failure_does_not_yield_or_terminate_another_session(self):
  child=MagicMock();child.poll.return_value=1
  with patch.object(session.subprocess,'Popen',return_value=child),patch.object(session.subprocess,'run') as run,patch.object(Path,'exists',return_value=False):
   with self.assertRaisesRegex(RuntimeError,'failed to start'):
    with session.ssh_session('aws-fixture'):self.fail('startup failure yielded')
   run.assert_not_called();child.terminate.assert_not_called()
 def test_invalid_alias_refused_before_spawn(self):
  with patch.object(session.subprocess,'Popen') as spawn:
   with self.assertRaises(ValueError):
    with session.ssh_session('-oBad'):self.fail()
   spawn.assert_not_called()
 def test_bundled_verifier_is_self_contained(self):
  code=verifier_source();self.assertNotIn("from './nrt_verify_concurrency.mjs'",code);self.assertEqual(code.count('async function mapLimit('),1);self.assertIn('await mapLimit(groups,2',code);self.assertIn('await mapLimit(profiles,2',code)
if __name__=='__main__':unittest.main()
