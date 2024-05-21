import argparse
import datetime
import json
import pathlib
from urllib.parse import urljoin

import boto3
import hyp3_sdk
import requests


def generate_ingest_message(hyp3_job_dict: dict, response_topic_arn: str):
    bucket = hyp3_job_dict['files'][0]['s3']['bucket']
    product_key = pathlib.Path(hyp3_job_dict['files'][0]['s3']['key'])
    response_topic_region = response_topic_arn.split(':')[3]

    return {
        'ProductName': product_key.stem,
        'DeliveryTime': datetime.datetime.now(tz=datetime.timezone.utc).replace(tzinfo=None).isoformat(),
        'ResponseTopic': {
            'Region': response_topic_region,
            'Arn': response_topic_arn,
        },
        'Browse': {
            'Bucket': bucket,
            'Key': str(product_key.with_suffix('.png')),
        },
        'Metadata': {
            'Bucket': bucket,
            'Key': str(product_key.with_suffix('.json')),
        },
        'Product': {
            'Bucket': bucket,
            'Key': str(product_key),
        },
    }


def get_cmr_product_ids(cmr_domain, collection_short_name):
    print(f'Querying {cmr_domain} for GUNW products in collection {collection_short_name}')
    session = requests.Session()
    cmr_url = urljoin(cmr_domain, '/search/granules.json')
    search_params = {
        'provider': 'ASF',
        'short_name': collection_short_name,
        'page_size': 2000,
    }
    headers = {}

    products = []
    while True:
        response = session.get(cmr_url, params=search_params, headers=headers)
        response.raise_for_status()
        products.extend(response.json()['feed']['entry'])
        if 'CMR-Search-After' not in response.headers:
            break
        headers = {'CMR-Search-After': response.headers['CMR-Search-After']}

    product_ids = [product['title'] for product in products]
    print(f'Found {len(product_ids)} products in CMR')
    return product_ids


def get_hyp3_jobs(hyp3_urls: list, job_type: str | list, start: datetime, username: str, password: str):
    print(f'Querying {hyp3_urls} as user {username} for GUNW products ({job_type} jobs) since {start}')
    jobs = []
    for hyp3_url in hyp3_urls:
        hyp3 = hyp3_sdk.HyP3(hyp3_url, username, password)
        response = hyp3.find_jobs(status_code='SUCCEEDED', job_type=job_type, start=start)
        jobs.extend(response)
    jobs = [job.to_dict() for job in jobs if not job.expired()]
    print(f'Found {len(jobs)} products')
    return jobs


def publish_messages(messages: list, topic_arn: str, dry_run: bool):
    print(f'Publishing {len(messages)} products to {topic_arn}')
    topic_region = topic_arn.split(':')[3]
    sns = boto3.client('sns', region_name=topic_region)
    for message in messages:
        print(f'Publishing {message["ProductName"]}')
        if not dry_run:
            sns.publish(
                TopicArn=topic_arn,
                Message=json.dumps(message),
            )


def main(hyp3_urls: list, job_type: str | list, start: datetime, cmr_domain: str, collection_short_name: str, topic_arn: str,
         username: str, password: str, dry_run: bool, response_topic_arn: str):
    hyp3_jobs = get_hyp3_jobs(hyp3_urls, job_type, start, username, password)
    ingest_messages = [generate_ingest_message(job, response_topic_arn) for job in hyp3_jobs]
    cmr_product_ids = set(get_cmr_product_ids(cmr_domain, collection_short_name))
    ingest_messages = [message for message in ingest_messages if message['ProductName'] not in cmr_product_ids]
    publish_messages(ingest_messages, topic_arn, dry_run)


def parse_datetime(s: str) -> datetime.datetime:
    dt = datetime.datetime.fromisoformat(s)
    if not dt.tzinfo:
        raise ValueError(f'Datetime {s} must include timezone')
    return dt


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cmr-domain', default='https://cmr.earthdata.nasa.gov',
                        choices=['https://cmr.earthdata.nasa.gov', 'https://cmr.uat.earthdata.nasa.gov'])
    parser.add_argument('--job-type', nargs='+', default=['INSAR_ISCE'],
                        choices=['INSAR_ISCE', 'ARIA_RAIDER'])
    parser.add_argument('--start', type=parse_datetime)
    parser.add_argument('--collection-short-name', default='ARIA_S1_GUNW',
                        choices=['ARIA_S1_GUNW'])
    parser.add_argument('--hyp3-urls', nargs='+',
                        default=['https://hyp3-a19-jpl.asf.alaska.edu', 'https://hyp3-tibet-jpl.asf.alaska.edu',
                                 'https://hyp3-nisar-jpl.asf.alaska.edu'],
                        choices=['https://hyp3-a19-jpl.asf.alaska.edu', 'https://hyp3-tibet-jpl.asf.alaska.edu',
                                 'https://hyp3-nisar-jpl.asf.alaska.edu'])
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('username')
    parser.add_argument('password')
    parser.add_argument('topic_arn')
    parser.add_argument('response_topic_arn')
    return parser.parse_args()


# assumes you have AWS credentials with permission to publish to the SNS topic
if __name__ == '__main__':
    args = get_args()
    main(args.hyp3_urls, args.job_type, args.start, args.cmr_domain, args.collection_short_name, args.topic_arn,
         args.username, args.password, args.dry_run, args.response_topic_arn)
