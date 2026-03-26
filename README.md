 Buckbot

Buckbot is a distributed rollback orchestration system for Wikimedia projects, designed to safely and efficiently process large-scale rollback and cleanup operations.

It is built to handle burst workloads (including tens of thousands of edits) while maintaining control, observability, and reliability.

---

##  Overview

Buckbot is at its heart an attempt at improving a rollback script to clean up a malfunctioning bot the grew wildly out of hand. 

---

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


---
### Jobs
Jobs are the primary working unit of chuckbot. Jobs are a collection of job items that are processed sequentially within the job by a celery worker. Multiple jobs can makeup a batch, 
Stored in `rollback_jobs`

A **job** represents a logical request, such as:
> “Rollback all edits from a specific user or diff”
however, there exists 2 classes of jobs: rollback and prep jobs.
rollback jobs are a list of job with a length defined by an envvar. they contain paramiters like who requested the job, it's staus, and if it's a dry run or not. It also can contain a batch number. 
**JOBS OCCASIONALLY ARE PERFORMED SEQUENTIALLY, BUT THIS IS NOT ENFORCED OR GUARANTEED** each job is put into a queue, where a worker will pick it up as soon as it can, and processing time does vary. a job with 1 item is much faster than 500 items. 

Jobs are orchestration units — they do not directly execute actions.

---

### Batches (`batch_id`)

A **batch** groups multiple jobs into a single logical operation.

This is necessary because large requests are split into multiple jobs.

Used for:
- Progress tracking
- UI display
- Notifications
- Aggregated status
every time you start a task, it's actions are put under one batch per request, so when you create a prep job, all rollback jobs created by it go under one batch. For a 100k edit task, that's 200 jobs of 500 items each. 
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


### Derived states (batch/UI)

- `active`
- `partial_success`
- `completed`

 **Important:**  
Item states are the source of truth.  
Job and batch states are derived from items.

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
→ 5,000 edits

Chunking:
→ Job A (1000 items)
→ Job B (1000 items)
→ Job C (1000 items)

All share:
batch_id = 1773857907459


---

## Chunking

Large operations are split into multiple jobs using `MAX_JOB_ITEMS`.

- Prevents oversized jobs
- Enables parallel processing
- Keeps execution stable

All chunked jobs share the same `batch_id`.

---

##  Execution Model

Buckbot uses distributed workers to process job items.

Workers:

- Select items with status `queued`
- Mark them as `running`
- Execute rollback actions
- Update status to `completed` or `failed`

Execution is:
- Sequential per item stream
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

### API Layer
- Flask application
- Handles authentication, validation, job creation

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

##  Example Job Payload

```json
{
  "command": "rollback",
  "targets": [
    { "title": "File:Example.jpg", "user": "VandalUser" }
  ],
  "maxRollbacksPerMinute": 10,
  "editSummary": "Reverting disruptive edits"
}
 Why Buckbot

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