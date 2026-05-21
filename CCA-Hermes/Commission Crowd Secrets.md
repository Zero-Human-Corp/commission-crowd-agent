**OCI ACCESS**

*Public IP*: 84.8.132.59
ssh your-user@84.8.132.59
ssh -i ~/.ssh/ssh-key-2026-04-20.key ubuntu@84.8.132.59
ssh oci

*SSH KEY*: ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIHENmDAgUzLBoTOd7PPmnzbipvPQEs1v8izxwelEmnA oci-zero-human

INSTANCE OCID: ocid1.instance.oc1.af-johannesburg-1.anvg4ljrd33bhaacescicrbcite45n7y3ovhhsacn765cx4xmxpxbkxgvznq

oci compute instance-console-connection create \
  --instance-id ocid1.instance.oc1.af-johannesburg-1.anvg4ljrd33bhaacescicrbcite45n7y3ovhhsacn765cx4xmxpxbkxgvznq \
  --ssh-public-key-file ~/.ssh/id_ed25519.pub \
  --wait-for-state SUCCEEDED

oci compute instance-console-connection connect \
  --instance-console-connection-id $(oci compute instance-console-connection list --instance-id ocid1.instance.oc1.af-johannesburg-1.anvg4ljrd33bhaacescicrbcite45n7y3ovhhsacn765cx4xmxpxbkxgvznq --query "data[0].id" --raw-output)


scp -r /user@Users-MBP ~ % scp -r /Users/user/Desktop/CCA\ Hermes\/* ubuntu@84.8.132.59:~/projects/commission-crowd-agent/

**Telegram Bot**

*Name*: CCA-Hermes-OCI
*Username*: t.me/ComCrowdBot
*API Token*: 8838375506:AAFMJeLjAvGrZ27hghhHXfEPExN76j1zAWc

