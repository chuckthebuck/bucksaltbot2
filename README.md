 Buckbot

Buckbot is a distributed rollback orchestration system for Wikimedia projects, designed to safely and efficiently process large-scale rollback and cleanup operations.

It is built to handle burst workloads (including tens of thousands of edits) while maintaining control, observability, and reliability.


##  Overview

Buckbot is at its heart an attempt at improving a rollback script to clean up a malfunctioning bot the grew wildly out of hand. 


##  Core Concepts

### tasks

a task is an action you need chuckbot to do, and are created by the rollback* APIs (the names start with rollback, such as "api/v1/rollback from diff", ) and take many different forms and inputs, with a focus on keeping calls from the web API lightweight, with as much processing being done by chuckbot as possible. Hence why there's 2 different ways to rollback massive amounts of user contribs with tiny api calls. 

---
### Job Items
the Job Item is the smallest unit of organisation within chuckbot. They are stored in a seprate table in mariaDB, and the rows unique within chuckbot, but the content's might not be (so the same page might be in the table many times.)

Stored in `rollback_job_items`

A **job item** represents a single rollback action:
- One page
- One user edit

 **Job items are what actually get executed.**
A Job item's data populates the mediawiki rollback command. 



### Jobs
Jobs are orchestration units in chuckbot. A job groups many job items under shared metadata (requester, dry-run flag, batch_id), and workers execute the items, not the job row itself. Multiple jobs can make up a batch.
Stored in `rollback_jobs`

A **job** represents a logical request, such as:
“Rollback all edits from a specific user or diff”.
There are two classes of jobs: rollback and prep jobs. Prep jobs expand lightweight API input into rollback items, then create one or more rollback jobs for execution. Rollback jobs are chunked by `MAX_JOB_ITEMS` (default 500), queued independently, and can run in parallel depending on worker availability.
Jobs in the same batch are not guaranteed to run sequentially.


### Batches (`batch_id`)

A **batch** groups multiple jobs into a single logical operation.

This is necessary because large requests are split into multiple jobs.

Used for:
- Progress tracking
- UI display
- Notifications
- Aggregated status
every time you start a task, it's actions are put under one batch per request, so when you create a prep job, all rollback jobs created by it go under one batch. For a 100k edit task, that's 200 jobs of 500 items each. Batchs don't have a definied size limit as batches are just defined as all jobs with the same batch ID entry in the jobs table. 
---

##  Lifecycle

Buckbot uses a multi-phase lifecycle.

### Job-level states

- `resolving` – tasks have been transformed into prep jobs, and are being expanded into job items  
- `queued` – a rollback job ready for execution  
- `running` – actively processing inside celery 
- `completed` – finished successfully  
- `failed` – finished with errors  (a single failed job item results in a failed job, but doesn't cause the job to stop. chuckbot will keep going through a failed item.)
- `canceled` – manually stopped  

### Item-level states (execution truth)

- `queued` – waiting to be claimed by a worker
- `running` – claimed by a worker and currently executing
- `completed` – rollback succeeded (or was already in desired state, e.g. `alreadyrolled`)
- `failed` – rollback attempt failed
- `canceled` – canceled before completion


### Derived states (batch/UI)

- `active`
- `partial_success`
- `completed`

 **Important:**
`rollback_job_items` is the runtime execution source of truth.
`rollback_jobs` and batch-level state are derived from item aggregates.

---

## 🔍 Resolution Phase

Some operations (especially `from-diff`) require a **resolution step**.

Example:

1. Input:
   - `oldid` or diff URL

2. Resolve:
   - Identify the user
   - Determine timestamp

3. Expand:
   - Find all affected edits

4. Create:
   - Many `rollback_job_items`

---

### Example


Input:
oldid = 12345

Expansion:
→ 12,300 edits

Chunking (default `MAX_JOB_ITEMS=500`):
→ Job A (500 items)
→ Job B (500 items)
→ ...
→ Job Y (300 items)

All share:
batch_id = 1773857907459


---

## Chunking

Large operations are split into multiple jobs using `MAX_JOB_ITEMS`.

- Prevents oversized jobs
- Enables parallel processing
- Keeps execution stable

All chunked jobs share the same `batch_id`.

Notes:
- Buckbot chunking is typically 500 items per rollback job.
- Upstream MediaWiki/API limits (for example 5000 in some contexts) are separate constraints and are handled during request resolution, not by increasing rollback job chunk size.

---

##  Execution Model

Buckbot uses distributed workers to process `rollback_job_items`.

Workers:

- Read job metadata (`rollback_jobs`) to check cancel/dry-run context
- Claim one item at a time from `rollback_job_items` where status is `queued`
- Transition claimed item to `running`
- Execute rollback action for that item
- Transition item to `completed`, `failed`, or `canceled`
- Derive final job status from item state counts

Execution is:
- Sequential per worker claim loop
- Parallel across workers

---

##  Rate Limiting

Rate limiting is defined at the **job level by chuckbots router** and enforced during execution. job item ratelimiting is also enforced by pywikibot to prevent excessive strain on the servers. 

- Config: `maxRollbacksPerMinute`
- Implementation: controlled delays between actions

This ensures:
- API stability
- Compliance with Wikimedia limits
- Safe large-scale execution

---

##  Permissions

Buckbot uses a granular permission model.

Controls include:

- Access to high-risk features (e.g. `from-diff`)
- Ability to create large batches
- Maintainer/admin overrides

Not all users can trigger all operations.

---

##  tie-ins to WMF

Buckbot integrates with Wikimedia workflows:

- On-wiki status updates
- Notifications for large jobs
- Optional user notifications after rollback

---

##  System Architecture

Buckbot runs on Toolforge and consists of:

### Web UI
-Gunicorn running a vue app for codex support. 
-Uses codex to create the UI, hence why we need to build node and python. 
(yes, the entire reason we build node.js and have to call NPM is because codex doesn't have native HTML support. no idea why, but at least node.js is the one language that can be added onto another language buildpack in heroku.)

### API Layer
- Flask application
- Handles authentication, validation, job creation and web routing 

### Queue
- Celery + Redis
- Distributes tasks to workers

### Workers
- Celery workers (Toolforge jobs)
- Execute rollback logic

### Database
- Toolforge MySQL
- Stores jobs, items, and batch relationships

### Execution
- Pywikibot / MediaWiki API

---

##  Example Request Payload (Input)

```json
{
  "command": "rollback",
  "targets": [
    { "title": "File:Example.jpg", "user": "VandalUser" }
  ],
  "maxRollbacksPerMinute": 10,
  "editSummary": "Reverting disruptive edits"
}
```

This JSON is request input, not the runtime execution source.
At runtime, Buckbot executes from database rows in `rollback_jobs` and `rollback_job_items`.

## Why Buckbot

Buckbot is designed to be:

Scalable – handles 10k–100k+ edits
Controlled – no uncontrolled automation
Fault-tolerant – item-level failure handling
Observable – batch + job + item tracking
Extensible – supports multiple workflows
# Important

Buckbot executes exactly what is requested. If it gets a diff and it's rollbackable, it can and will rollback it. 

It:

does not evaluate context
does not make decisions

Human oversight is always required.
See:

DEPLOYMENT_DOCS_INDEX.md
DEPLOYMENT_SUMMARY.md
FEATURES_GRANULAR_PERMISSIONS.md
