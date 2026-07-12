#!/usr/bin/env python3
import importlib.util,json,pathlib,shutil,tempfile,unittest
HERE=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('bench',HERE/'closure-benchmark.py'); b=importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
class BenchmarkNegative(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(); self.root=pathlib.Path(self.t.name)/'fixtures'; shutil.copytree(HERE/'fixtures/closure-benchmarks',self.root)
 def tearDown(self): self.t.cleanup()
 def bad(self,fn): fn(self.root/'clean-plan'); self.assertFalse(b.run(self.root)['passed'])
 def test_extra_launch_fails(self):
  def mutate(d):
   p=d/'new-events.jsonl'; p.write_text(p.read_text()+'{"at_ms":999,"event":"provider_launch"}\n')
  mutate(self.root/'migration-concurrency'); self.assertFalse(b.run(self.root)['passed'])
 def test_duplicate_id_fails(self):
  def mutate(d):
   p=d/'registry.json'; x=json.loads(p.read_text()); x['findings']=[{'finding_id':'CX-0001'},{'finding_id':'CX-0001'}]; p.write_text(json.dumps(x))
  self.bad(mutate)
 def test_plan_mutation_fails(self): self.bad(lambda d:(d/'reviewed-plan.md').write_text('mutated'))
 def test_dishonest_outcome_fails(self):
  def mutate(d):
   p=d/'result.json'; x=json.loads(p.read_text()); x['outcome']='blocked'; p.write_text(json.dumps(x))
  self.bad(mutate)
 def test_invalid_evidence_fails(self):
  def mutate(d):
   p=d/'result.json'; x=json.loads(p.read_text()); x['verifications']=[{'finding_id':'CX-0001','verdict':'closed','evidence':[],'reason':'x'}]; p.write_text(json.dumps(x))
  self.bad(mutate)
if __name__=='__main__': unittest.main(verbosity=2)
