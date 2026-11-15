"""Round 2: clear the 30 remaining CodeQL alerts on agentflow (empty-except x11, ineffectual-statement x30... adjusted: 11+30=41? API said 30 total)."""
import io, re, sys

def rd(p): return io.open(p, encoding='utf-8').read()
def wr(p, s): io.open(p, 'w', encoding='utf-8', newline='\n').write(s)

# ---- 1) module loggers ----
for p in ('agentflow/cloud/aws.py', 'agentflow/runners/ecs.py', 'agentflow/orchestrator.py'):
    s = rd(p)
    if 'logging.getLogger' in s:
        continue
    lines = s.split('\n')
    first_def = next(i for i, l in enumerate(lines) if re.match(r'^(def |class |async def )', l))
    last_imp = max(i for i, l in enumerate(lines[:first_def]) if re.match(r'^(import |from )', l))
    lines.insert(last_imp + 1, 'import logging')
    lines.insert(last_imp + 2, '')
    lines.insert(last_imp + 3, 'logger = logging.getLogger(__name__)')
    wr(p, '\n'.join(lines))
    print('logger added:', p)

def swap_pass(path, except_line, body):
    """Replace the `pass` body following the except on line N (1-based) with body."""
    s = rd(path)
    lines = s.split('\n')
    idx = except_line - 1
    assert re.match(r'^\s*except\b', lines[idx]), (path, except_line, lines[idx])
    # find the pass body line (immediately after except, possibly docstring/comment later)
    j = idx + 1
    while j < len(lines) and (lines[j].strip() == '' or lines[j].strip().startswith('#')):
        j += 1
    assert lines[j].strip() == 'pass', (path, except_line, lines[j])
    indent = lines[j][:len(lines[j]) - len(lines[j].lstrip())]
    lines[j] = indent + body
    wr(path, '\n'.join(lines))
    print('pass->stmt:', path, except_line)

# ---- 2) empty excepts ----
swap_pass('agentflow/cloud/aws.py', 132, 'logger.debug("Unreadable codex auth file; continuing without it", exc_info=True)')
swap_pass('agentflow/cloud/aws.py', 146, 'logger.debug("Unreadable codex config; continuing without it", exc_info=True)')
swap_pass('agentflow/cloud/aws.py', 162, 'logger.debug("Unreadable claude credentials; continuing without them", exc_info=True)')
swap_pass('agentflow/runners/ecs.py', 39, 'logger.debug("ECR repository already exists: %s", repo_name)')
swap_pass('agentflow/runners/ecs.py', 83, 'logger.debug("Could not check cluster status", exc_info=True)')
swap_pass('agentflow/runners/ecs.py', 93, 'logger.debug("Log group already exists: %s", log_group)')
swap_pass('agentflow/runners/ecs.py', 232, 'logger.debug("Failed to read a page of log events", exc_info=True)')
swap_pass('agentflow/runners/ecs.py', 254, 'logger.debug("Failed to read a page of log events", exc_info=True)')
swap_pass('agentflow/orchestrator.py', 109, 'logger.debug("No runner registered for kind", exc_info=True)')
swap_pass('agentflow/orchestrator.py', 165, 'logger.debug("No shared manager for kind", exc_info=True)')
swap_pass('agentflow/orchestrator.py', 726, 'logger.debug("Could not compute worktree diff", exc_info=True)')
swap_pass('agentflow/orchestrator.py', 739, 'logger.debug("Could not remove worktree", exc_info=True)')

# ---- 3) ineffectual statements: `_ = ` prefix ----
SITES = [
    'agentflow/runners/local.py:350', 'agentflow/runners/local.py:365',
    'tests/test_runners.py:600',
    'examples/airflow_like.py:33', 'examples/airflow_like.py:34',
    'examples/airflow_like_fuzz_batched.py:162', 'examples/airflow_like_fuzz_batched.py:163', 'examples/airflow_like_fuzz_batched.py:164',
    'examples/airflow_like_fuzz_grouped.py:168', 'examples/airflow_like_fuzz_grouped.py:169', 'examples/airflow_like_fuzz_grouped.py:170',
    'examples/code_review.py:49', 'examples/code_review.py:50',
    'examples/dep_audit.py:45', 'examples/ec2_remote.py:24', 'examples/ecs_fargate.py:20',
    'examples/iterative_impl.py:38', 'examples/iterative_impl.py:40',
    'examples/multi_agent_debate.py:41', 'examples/multi_agent_debate.py:42', 'examples/multi_agent_debate.py:43',
    'examples/release_check.py:27', 'examples/test_gap.py:50', 'examples/test_gap.py:51',
    'tests/test_dsl.py:132', 'tests/test_dsl.py:133', 'tests/test_dsl.py:204', 'tests/test_dsl.py:205',
    'tests/test_dsl.py:282', 'tests/test_dsl.py:283', 'tests/test_dsl.py:284',
    'tests/test_dsl.py:349', 'tests/test_dsl.py:350', 'tests/test_dsl.py:351',
]
by_file = {}
for spec in SITES:
    path, line = spec.rsplit(':', 1)
    by_file.setdefault(path, []).append(int(line))

for path, lns in by_file.items():
    s = rd(path)
    lines = s.split('\n')
    for ln in lns:
        cur = lines[ln - 1]
        stripped = cur.lstrip()
        indent = cur[:len(cur) - len(stripped)]
        assert ('>>' in stripped) or stripped.startswith('await '), (path, ln, cur)
        lines[ln - 1] = f'{indent}_ = {stripped}'
    wr(path, '\n'.join(lines))
    print('ineffectual fixed:', path, len(lns))

print('DONE')
