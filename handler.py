from saral_utils.extractor.dynamo import DynamoDB
from saral_utils.extractor.dynamo_queries import DynamoQueries
from saral_utils.utils.env import get_env_var, create_env_api_url
from saral_utils.utils.qna import normalize_options, image_exist
from saral_utils.utils.frontend import ShareLinks

from pandas import DataFrame
from botocore.exceptions import ClientError
import random
import markdown
import boto3
import pandas as pd
from datetime import datetime
import urllib

def deparse_dynamo_colm(df:DataFrame, col: str, key: str) -> DataFrame:
    df[col] = df[col].apply(lambda x: x[key])
    return df


def emailer(event, context):
    print(event)
    data = event
    emailId = data['emailId']

    # fetch question from dynamodb
    env = get_env_var(env='MY_ENV')
    region = get_env_var(env='MY_REGION')
    que_table = f'saral-questions-{env}'
    sent_que_table = f'saral-questions-sent-{env}'
    user_tble = f'registered-users-{env}'
    
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
    
    # fetch user information 
    user_db = DynamoDB(table=user_tble, env=env, region=region)
    user_info = user_db.query(KeyConditionExpression='emailId = :emailId', ExpressionAttributeValues={':emailId': {'S': emailId}})
    user_created_time = user_info[0]['createdAt']['S']
    user_created_time = datetime.strptime(user_created_time, '%Y-%m-%d %H:%M:%S')
    n_days = (datetime.now() - user_created_time).days
    remainder = n_days % len(r_que_wo_imgs)

    # finding the unique question
    que_df = pd.DataFrame(r_que_wo_imgs)
    que_df = deparse_dynamo_colm(df=que_df, col='createdAt', key='S')
    que_df['createdAt'] = pd.to_datetime(que_df['createdAt'])
    que_df = que_df.sort_values(by='createdAt', ascending=True)
    question = que_df.iloc[remainder, :]

    que_text = question['questionText']['S']
    que_id = question['id']['S']
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
    answer_link = create_env_api_url(url=f"answer.saral.club/qna/{que_id}")
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
    
    return response