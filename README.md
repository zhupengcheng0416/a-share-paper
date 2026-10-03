# A������ģ���� �� ����Ŀ���ϰ�

���ƶˣ�https://a-share-paper-control.zhupengcheng0416.workers.dev

2026-10-03���ѽ�����ָ��������GitHub��Ŀ�ķ���ģ�飬����GitHub��׼Ubuntu����������ƶ���֤��17��Python����+8��Worker���ȫ��ͨ��������֤��¼��https://github.com/zhupengcheng0416/a-share-paper/actions/runs/37128995299 ��Cloudflareֱ����;RESTֻ����Ȩ��A��ģ���˻���ȡ��ʵ��ɹ�����ǰû��ʵʱȫ�г����ݡ��Զ�ģ�⽻�׻��ʼ�Ͷ�ݣ�û�ж����ύ��

## ԭ������ܹ�

- �Ƽ���������ֵ��70��Ԫ������Ʊ�أ���¼��ҵ����ֵ���Ʊ��������ڼ�������Դ��
- �̶��汾�Ĺ�����ģ�ͣ����ô�ģ���ٳ��������ס�
- �ų�ST��ͣ�ơ��¹ɺ͵������ԣ�ȱʧ/��Ч/δ��������ϡ�
- ���Ԥ�㡢�ֽ�ռ�á��ظ����������۶�������SQLite���߿��ա�
- ������SIMULATE��Ԥ��0Ԫ�������ø���ģ��/����/��������
- ����Ŀ��Ϊ���Թػ����ƶ����У��ʼ�����zhupengcheng0416@163.com��

��ϸģ�顢����ƶ˲�֡��ӿڼ�δ������� [ARCHITECTURE.md](ARCHITECTURE.md)�����в���ֲδ��֤������ʤ�ʣ�Ҳ����ԭ�����ڻ�����߼�����A�ɽ��׻ز⡣

## ��ǰ�����й���

`paper/integrations.py`��ԭ��V3Fusion֧��������AlphaMaster65�����붳�ṫʽ��PA_Agent������K�߿͹۽ṹ��ʵ�������о�������������о��źŲ����ύ������

`paper/mining.py`��CPU�н�����/�������������256��ѡ��ѵ��/��֤/�����������ԷֶΣ����Ԥ�����ϵ���Ͳ��ɽ��׵��о��������ǿ��ѧϰѵ����δ���롣

`paper/core.py`��ԭѡ�ɹ��������Ԥ�㣻`config.json` ��ģ�ⷶΧ�������Ҫ���70��Ԫ�߽�����Ϊ���̲ݰ���δ������ز⡣

`cloudflare/worker.mjs`����Ȩ���ƶˡ���;�ƶ�ֻ��Ԥ�졣���Ʊ�����Cloudflare����secret�����ڽ������ڡ�

`.github/workflows/research.yml`����ѹ����ֿ��׼Ubuntu runner��֤���������ѷ������ɹ����У��޸���ģ�͵��á��޸���runner����artifact�ϴ���

`vendor/`��`upstream-lock.json`��`LICENSE`��`NOTICE.md`��������Դ�������ύ��Դ���ϣ������֤��һ���޽��������޸ļ�¼��

## ��֤������

Python3.12������Ŀ¼ִ�У�

```text
python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements-research.txt
python -m unittest discover -s tests -v
node tests/test_worker.mjs
python -m paper.service check
python -m paper.integrations --input validated-session.json --output state/report.json
python -m paper.mining --input one-symbol-history.json --output state/research-factor.json
```

17��Python������8��Worker���ͨ��������ʹ����ȷ��ǵĺϳ����ݣ���������ʵȫ�г���ȯ�̳ɽ���֤��

�������dataset_kind=completed_session��session��source��coverage��stocks��ÿֻ��Ʊ��code/name/industry/market_cap_cny/is_st/suspended/listing_days/roe/fundamental_asof/session/source/adjust_mode/bars��ÿ�����ߺ�date/open/high/low/close/volume/turnover_cny/closed����������260�����ھ�����700����fundamental_asof��Ϊ�����ɻ�����ڣ���Ȩ�ھ�����ʱ��֤�ݣ��Ӽ����ܳ�Ϊȫ�г���

## ����������

Դ�����ƶ���֤�Ѳ����� https://github.com/zhupengcheng0416/a-share-paper ��������ʵ������鲢��֤�����г����ǡ����Իز⡢A��T+1/�ǵ�ͣ/�ɽ����á�EXIT�붩�����ˡ��ʼ�outbox��ģ��дȨ�޼�С��ģ���ܡ�

`deploy/`��`paper/futu_gateway.py` ��������Linux/OpenD������Ϊ�ο�����ǰ��Ҫ���������VM��������Oracleע��·������Ҫ·��ΪCloudflare REST���ƶ�+���Python�ƶ���������
