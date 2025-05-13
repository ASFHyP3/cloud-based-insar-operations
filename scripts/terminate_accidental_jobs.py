import boto3
from tqdm.auto import tqdm


JOB_QUEUE_ARN = 'arn:aws:batch:us-west-2:176245438256:job-queue/BatchJobQueue-fzRFEEEvL4l1jLRp'
REASON = '2024-06-14 terminating accidental jobs'

batch = boto3.client('batch')


def get_batch_jobs(status: str) -> list[dict]:
    paginator = batch.get_paginator('list_jobs')
    page_iterator = paginator.paginate(
        jobQueue=JOB_QUEUE_ARN,
        jobStatus=status,
    )
    return [job for page in page_iterator for job in page['jobSummaryList']]


def terminate_job(batch_job_id: str) -> None:
    batch.terminate_job(jobId=batch_job_id, reason=REASON)


def main() -> None:
    batch_jobs = get_batch_jobs('SUBMITTED') + get_batch_jobs('PENDING') + get_batch_jobs('RUNNABLE')
    for batch_job in tqdm(batch_jobs):
        terminate_job(batch_job['jobId'])


if __name__ == '__main__':
    main()
