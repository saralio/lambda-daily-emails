from multiprocessing.connection import Client
import random
import markdown
from saral_utils.extractor.dynamo import DynamoDB
from saral_utils.extractor.dynamo_queries import DynamoQueries
from saral_utils.utils.env import get_env_var
from botocore.exceptions import ClientError
import boto3
import pandas as pd
from typing import List, Dict
from datetime import datetime

def normalize_options(options: List) -> List[Dict[str, str]]:
    """normalizes a dictionary from dynamodb, specific to options

    Args:
        options (List[str]): options of a question from table `saral-questions`

    Returns:
        List[Dict[str, str]]: a list with normalized options in dictonary format. Of the form [{'is_correct':..., 'text':..., 'image_path_exists':...}]
    """    
    flat = []
    for option in options:
        opt = {}
        option = option['M']
        opt['is_correct'] = option['correct']['BOOL']
        opt['text'] = option['text']['S']
        opt['image_path_exist'] = True if 'S' in option['imagePath'].keys() else False

        flat.append(opt)
    return flat

def image_exist(question: Dict) -> bool:
    """for a given question from `saral-questions` table check if the question has any image associated with it whether in question or in option

    Args:
        question (Dict): question data

    Returns:
        bool: True if image exist either in question text or in options otherwise False
    """
    que_image_exist = True if 'L' in question['questionImagePath'].keys(
    ) else False

    options = question['options']['L']
    flatten_option = normalize_options(options)
    opt_image_exist = any([True for opt in flatten_option if opt['image_path_exist']])

    if que_image_exist or opt_image_exist:
        return True
    else:
        return False


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
    # TODO: [SAR-33] add support for questions with images

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

    #TODO: [SAR-36] add view answer link
    #TODO: [SAR-40] add unsubscribe link
    tweet="I%20am%20enjoying%20the%20daily%20questions%20from%20%40data_question%20in%20my%20inbox%2C%20if%20you%20would%20like%20to%20receive%20one%20daily%20question%20on%20%23RStats%20programming%2C%20don%27t%20forget%20to%20signup%20at%20https%3A%2F%2Fwww.saral.club%20"

    html_text = f"## Here's your daily dose of [#RStats](https://www.twitter.com/data_question)\n\n### Question\n{que_text}\n\n#### Options\n{option_text} \
    \n\n*To view the answer click [here](#href)*\n\n\n*If you liked the question please consider supporting by [sharing](https://twitter.com/intent/tweet?text={tweet}) or by making a [donation](https://paypal.me/mohit2013?country.x=IN&locale.x=en_GB). \
    Your donation helps us keep the services afloat. Be sure to follow us on [twitter](https://www.twitter.com/data_question) and [Youtube](https://www.youtube.com/channel/UChZfYRQRGADaLtgdYaB0YBg) for regular updates.*\
    \n\n*To unsubscribe click [here](#href)*"

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
    except ClientError as error:
        print(f'Not able to upload sent question to `saral-questions-sent` table. Error returned: {error}')

    response = {"statuscode": 200}

    return response