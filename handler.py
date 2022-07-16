from saral_utils.extractor.dynamo import DynamoDB
from saral_utils.extractor.dynamo_queries import DynamoQueries
from saral_utils.utils.env import get_env_var, create_env_api_url
from saral_utils.utils.qna import normalize_options, image_exist
from saral_utils.utils.frontend import ShareLinks

from botocore.exceptions import ClientError
import random
import markdown
import boto3
import pandas as pd
from datetime import datetime
import urllib

def emailer(event, context):
    print(event)
    data = event
    emailId = data['emailId']

    # fetch question from dynamodb
    env = get_env_var(env='MY_ENV')
    region = get_env_var(env='MY_REGION')
    que_table = f'saral-questions-{env}'
    sent_que_table = f'saral-questions-sent-{env}'
    
    que_db = DynamoDB(table=que_table, env=env, region=region)
    r_attr = DynamoQueries.r_prog_que_attr_values
    r_filt = DynamoQueries.r_prog_que_filter_expr
    r_key = DynamoQueries.r_prog_que_key_cond_expr
    r_questions = que_db.query(KeyConditionExpression=r_key,
                           ExpressionAttributeValues=r_attr, FilterExpression=r_filt)

    # exclude all questions with images in them
    print(f'Total available R questions: {len(r_questions)}')
    r_que_wo_imgs = [que for que in r_questions if not image_exist(que)]
    print(f'Total R questions without images: {len(r_que_wo_imgs)}')
    r_que_ids = [que['id']['S'] for que in r_que_wo_imgs]
    
    que_sent_db = DynamoDB(table=sent_que_table, env=env, region=region)
    key_cond_expr = 'emailId = :emailId'
    expr_attr = {':emailId': {'S': emailId}}
    que_sent = que_sent_db.query(KeyConditionExpression=key_cond_expr, ExpressionAttributeValues=expr_attr)
    que_sent_ids = [que['questionId']['S'] for que in que_sent]

    que_not_sent = list(set(r_que_ids) - set(que_sent_ids))


    # select a question from queries only select questions without images
    if len(que_not_sent) == 0:
        print('No more unique questions left, all questions already sent')
        que_df = pd.json_normalize(que_sent)
        first_row = que_df.sort_values(by='sentCount.N', ascending=True).iloc[0, :]
        que_id_min_sent = first_row['questionId.S']
        sent_count = first_row['sentCount.N']
        question = que_db.get_item(key={'topic': {'S': 'Programming'}, 'id': {'S': que_id_min_sent}}) # type: ignore
        ques_sent_payload = {'emailId': emailId, 'questionId': que_id_min_sent, 'sentCount': int(sent_count) + 1}
        print(f'Data to write to saral-questions-sent: {ques_sent_payload}')
    else:
        print(f'Question ids not sent so far: {que_not_sent}')
        ques_not_sent_id = random.choice(que_not_sent)
        print(f'Selected question with id: {ques_not_sent_id}')
        question = que_db.get_item(key={'topic': {'S': 'Programming'}, 'id': {'S': ques_not_sent_id}}) # type: ignore
        ques_id = question['id']['S']
        ques_sent_payload = {'emailId': emailId, 'questionId': ques_id, 'sentCount': 1}    
    
    que_text = question['questionText']['S']
    flatten_options = normalize_options(question['options']['L'])
    option_text = ""
    if len(flatten_options) == 0:
        option_text = "1. No options are provided for this question"
    else:
        for i, opt in enumerate(flatten_options):
            option_text += f"{str(i+1)}. {opt['text']}\n"


    # add links
    sl = ShareLinks(email_id=emailId)
    twitter_account_link = sl.twitter_account_link
    donation_link = sl.donation_link
    youtube_link = sl.youtube_link
    unsubscribe_link = sl.unsubscribe_link
    website_link = sl.saral_website_link
    sharing_link = sl.sharing_link
    answer_link = create_env_api_url(url=f"answer.saral.club/qna/{ques_sent_payload['questionId']}")
    tweet_text = f"Check out this question by @data_question on #RStats: {answer_link}.\nYou can subscribe at {website_link} to receive such questions daily in your inbox."
    tweet=urllib.parse.quote_plus(tweet_text) #type:ignore
    tweet_share_link = f"{sharing_link}{tweet}"

    html_text = f"## Here's your daily dose of [#RStats]({twitter_account_link})\n\n### Question\n{que_text}\n\n#### Options\n{option_text} \
    \n\n*To view the answer click [here]({answer_link}).*\n\n\n*If you liked the question please consider supporting by [sharing]({tweet_share_link}) or by making a [donation]({donation_link}). \
    Your donation helps us to keep the services afloat. Be sure to follow us on [Twitter]({twitter_account_link}) and [YouTube]({youtube_link}) for regular updates.*\
    \n\n*To unsubscribe click [here]({unsubscribe_link}).*"

    # html = html_text
    html = markdown.markdown(html_text, extensions=['markdown.extensions.fenced_code', 'markdown.extensions.codehilite'], extension_configs={
                             'markdown.extensions.codehilite': {'pygments_style': 'material', 'noclasses': True, 'cssstyles': 'padding: 10px 10px 10px 20px'}})

    ses_client = boto3.client('ses')
    CHARSET = "UTF-8"

    print(html_text)
    try:
        response = ses_client.send_email(
            Destination={
                "ToAddresses": [emailId]
            },
            Message={
                "Body": {
                    "Html": {
                        "Charset": CHARSET,
                        "Data": html
                    }
                },
                "Subject": {
                    "Charset": CHARSET,
                    "Data": "#RStats Question A Day"
                }
            },
            Source="Saral<dailyquestion@saral.club>"
        )
    except ClientError as error:
        print(error)
        raise RuntimeError(error)
    
    # upload question sent payload to saral-questions-sent table
    try:
        response = que_sent_db.put_item(
            payload={
                'emailId': {'S': ques_sent_payload['emailId']},
                'questionId': {'S': ques_sent_payload['questionId']},
                'sentCount': {'N': str(ques_sent_payload['sentCount'])},
                'dateSent': {'S': datetime.now().strftime('%Y-%m-%d')}
            }
        )
        response = {"statusCode": 200}
    except ClientError as error:
        print(f'Not able to upload sent question to `saral-questions-sent` table. Error returned: {error}')
        response = {"statusCode": 500}

    return response