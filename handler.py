import random
import markdown
from saral_utils.extractor.dynamo import DynamoDB
from saral_utils.extractor.dynamo_queries import DynamoQueries
from saral_utils.utils.env import get_env_var
from botocore.exceptions import ClientError
import boto3


def emailer(event, context):
    print(event)
    data = event

    # TODO: [SAR-32] add code for not selecting already posted questions
    # fetch question from dynamodb
    env = get_env_var(env='MY_ENV')
    region = get_env_var(env='MY_REGION')
    table = f'saral-questions-{env}'

    db = DynamoDB(table=table, env=env, region=region)
    r_attr = DynamoQueries.r_prog_que_attr_values
    r_filt = DynamoQueries.r_prog_que_filter_expr
    r_key = DynamoQueries.r_prog_que_key_cond_expr

    r_questions = db.query(KeyConditionExpression=r_key,
                           ExpressionAttributeValues=r_attr, FilterExpression=r_filt)['Items']

    # select a question from queries only select questions without images
    # TODO: [SAR-33] add support for questions with images
    while True:
        question = random.choice(r_questions)
        question_id = question['id']['S']
        que_image_exist = True if 'L' in question['questionImagePath'].keys(
        ) else False
        options = question['options']['L']
        flatten_options = []
        for option in options:
            opt = {}
            option = option['M']
            opt['is_correct'] = option['correct']['BOOL']
            opt['text'] = option['text']['S']
            opt['image_path_exist'] = True if 'S' in option['imagePath'].keys() else False

            flatten_options.append(opt)

        option_image_exist = any(
            [True for opt in flatten_options if opt['image_path_exist']])

        if que_image_exist or option_image_exist:
            continue
        else:
            print(f'selected question id: {question_id}')
            break

    que_text = question['questionText']['S']

    option_text = ""
    if len(flatten_options) == 0:
        option_text = "1. No options are provided for this question"
    else:
        for i, opt in enumerate(flatten_options):
            option_text += f"{str(i+1)}. {opt['text']}\n"

    html_text = f"## Here's your daily dose of [#RStats](https://www.twitter.com/data_question)\n\n### Question\n{que_text}\n\n#### Options\n{option_text} \
    \n\n*To view the answer click [here](#href)*\n\n\n*If you liked the question please consider supporting by [sharing](#href) or by making a [donation](#href). \
    Your donation helps us keep the services afloat. Be sure to follow us on [twitter](https://www.twitter.com/data_question) and [Youtube](#href) for regular updates.*\
    \n\n*To unsubscribe click [here](#href)*"

    html = markdown.markdown(html_text, extensions=['markdown.extensions.fenced_code', 'markdown.extensions.codehilite'], extension_configs={
                             'markdown.extensions.codehilite': {'pygments_style': 'material', 'noclasses': True, 'cssstyles': 'padding: 10px 10px 10px 20px'}})

    ses_client = boto3.client('ses')
    CHARSET = "UTF-8"
    emailId = data['emailId']

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
                    "Data": "Daily Topics to Rewise"
                }
            },
            Source="mohitlakshya@gmail.com"
        )
    except ClientError as error:
        print(error)
        raise RuntimeError(error)

    print("Email Sent successfully")
