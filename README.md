Runs as a cron job to send out the notifications to sqs service

when user registers -> create a rule for his/her selected time
attach that event rule to the lambda which sends email
that lambda should receive a client id
check in dynamo db what all questions are send to that client and then send the one which is not sent
 