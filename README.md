# Support agent approval policy

Kortix is the open-source AI Operating System, and this repository is a working
approval policy for a customer support agent that reads everything and writes
almost nothing. It is the file pair a reviewer asks for in a support-agent
review: the `kortix.yaml` that governs the calls, and a small script that prints
which calls in a queue a person would be asked about.

Most support-agent policies are written a tier at a time: read, limited write,
escalate. That phrasing survives a vendor questionnaire and decides nothing.
The three systems a support thread touches are not one risk class. Searching a
codebase for a bug's code path leaves the building in no direction. Replying in
a thread is visible, correctable, and the customer can answer it. Moving money
is neither visible nor correctable, and it happens once.

So the boundary in this policy is a call, matched with an argument condition:

```yaml
  - match: "stripe.create_refund"
    action: always_run
    conditions:
      - arg: reason
        match: "duplicate"

  - match: "stripe.create_refund"
    action: require_approval
```

A duplicate charge is arithmetic: the customer was charged twice, the invoices
show it, and the refund is the correction. It runs. A refund with any other
reason is a judgment about the customer relationship — goodwill, a discount
after a bad week, a churn save — and pricing that judgment is the part an agent
should not do alone. It waits for a person. The refund is the same amount on
both paths; only the reason decides who signs off.

The rest of the file follows that logic. `default_mode: risk` runs reads and
holds writes, so anything a rule misses still stops before it changes something.
Replies and internal notes run because a thread can absorb a correction.
`stripe.update_subscription` waits because a plan change bills every month from
now on. `*.delete_*` is blocked outright: a deleted customer record and a
deleted thread are the two things a support desk cannot argue its way back from.

## Run the checker

`check_policy.py` reads the policy out of `kortix.yaml` and resolves a queue of
calls against it, in the documented order: project-wide rules first, first match
wins, `default_mode` last. Python 3 standard library only, no install.

```
$ python3 check_policy.py
default_mode: risk   approvals.ttl: 4h
call                           decision  because
github.search_code             run       rule github.*
stripe.list_invoices           run       rule stripe.list_*
stripe.get_charge              run       rule stripe.get_*
helpdesk.reply_to_thread       run       rule helpdesk.reply_to_thread
helpdesk.add_note              run       rule helpdesk.add_note
stripe.create_refund           run       rule stripe.create_refund + condition
stripe.create_refund           hold      rule stripe.create_refund
stripe.update_subscription     hold      rule stripe.update_subscription
helpdesk.escalate_to_engineer  hold      default_mode: risk (write)
stripe.delete_customer         block     rule *.delete_*

10 calls: 6 run without a person, 3 wait for one, 1 blocked.
```

The two `stripe.create_refund` rows are the whole argument. Same tool, same
kind of amount, opposite outcomes, and one line apart in the file. The fixture
in `examples/support-calls.json` is the ten calls a thread actually makes,
including the one nobody wrote a rule for: `helpdesk.escalate_to_engineer`
falls through to `default_mode: risk` and waits, which is the correct answer for
a call the author did not think about.

Change the queue, not the script, to test another policy: point `--calls` at
your own fixture. `--json` prints the resolved rules beside each decision.

## What this is not

- Not the enforcement point. Kortix evaluates these rules when the call is made
  and its decision is the one that runs; this script reads the same file the
  same way so a reviewer can see the answers before a session exists.
- The `default_mode: risk` read/write split here is a verb heuristic
  (`get`, `list`, `search`, `read` and similar are reads). The platform
  classifies each action from the connector's own tool list.
- A condition's `match` is a glob, so it cannot express a range. An amount
  threshold needs its own rule, not a glob.
- Connector-level `policies:` blocks are not parsed. This manifest keeps every
  rule project-wide, which is also how it reads best in review.

## Where the pieces come from

- The keys, the rule order and `approvals.ttl`: the manifest reference at
  https://kortix.com/docs/project/manifest
- How a held call appears in a session (`202`, `pending_approval`, an approval
  URL), and what an approval covers: https://kortix.com/docs/connect/connectors
- The argument this policy makes, worked through the ten-call queue and the two
  refund rules: https://kortix.com/blog/what-a-support-agent-may-do
- The support setup this policy is written for — Plain, the codebase and
  Stripe, one sandbox per thread: https://kortix.com/use-cases/customer-support
- The help-desk connector URL is a placeholder. Replace it with your help desk's
  MCP server; Kortix holds the credential and the sandbox never sees it. The
  GitHub connector is Composio's managed app, and Stripe is connected from its
  published OpenAPI document.

The agent whose behaviour this policy bounds is in `agents/support.md`. Its
instructions and its permissions are separate files, in one repository, so a
change to either arrives as a diff someone reviews.
