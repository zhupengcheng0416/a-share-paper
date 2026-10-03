# ����Ŀ����������ò���

����·��ʱ��һ�µ������� A ������/Ԫ���� �� ������Ʊ�� �� V3 ֧������ + AlphaMaster ����/��ʽ + PA_Agent �͹۽ṹ��ʵ �� �̶����������Ԥ�� �� ���߿��� �� ��;ģ�ⶩ���������� �� �ʼ�������

## ʵ�ʽ��������ģ��

| ��Ŀ | �������� | ��ǰ��֤��Χ |
|---|---|---|
| Detect_support_and_resistance_levels | ԭ�� SREngine/V3Fusion��ATR��������ᡢ�ɽ������� | 320���ϳ����߼�⣻����ֲδ��֤��ʤ�ʱ궨�ļ� |
| AlphaMaster | ԭ��65���������ʱ��汾��StackVM�����빫ʽִ�� | ���ǰ׺���ԣ�CPU�н�����������ѵ��/��֤/�������Էֶ� |
| PA_Agent | ԭ�������̿��ա�EMA/ATR��K�߼��Ρ��г��ṹ������ʵ | �޽������У�����͹����ݽ��룻LLM����0�� |

`upstream-lock.json` �̶������ύ��ÿ����Դ�ļ� SHA256����ѡԴ�뼰ԭʼ����֤������ `vendor/`��PA_Agent ���߰���һ����¼�����޸ģ�EventBus ��Ϊ���赼�룬�����ƶ˼������ Qt���������Դ��δ�޸ġ�����Դ���湤�������ṩ������������ GPL/AGPL ����֤��

`paper/integrations.py` ֧������������SQLite��������/����������������ʹ��ԭ�����ļ�Э�飻����Ҫ������260���������ߡ�ÿ�� `closed:true`��`adjust_mode` Ϊ `hfq_point_in_time` �� `qfq_asof_session`�������ھ�����������������ʵ����֤���ֶα�ǩ���ܴ������ݺ��顣��ֹ����ǰǰ��Ȩ������Ϊ��ʷʱ��ز����ݡ�

`paper/mining.py` �ṩ���CPU�н�������ʹ���������������ӣ����256����ѡ��ѵ��ɸѡǰ10����֤ѡһ������������ֻ����һ�Σ��ֶμ����5����Ŀ�����źŵ���֮��Ĵ��տ��̵�����һ�����տ������档�����Ԥ�����ϵ�������ǽ��׻ز����档��������ǿ��ѧϰѵ��������Դ�룬��δ�����ƶ�������ԭ�����/�ڻ��������۲���ֱ������A�ɡ���ǰ�����ǵ�ֻ�����Ʊ�о���δ����ȫ�г��ھ���ɡ�

�����ھ����Ĭ�� `research_only`����ֹ�Զ�����Ϊ�ɽ���ģ�͡���ȡ��ʽ�˶Դʱ��������ύ���������ڣ�ȱʧģ������ʾ65�����Ѽ��㣬��û��ģ���źš�����ɨ���ԭ���� ENTRY ��¼Ϊ `base_signal`���о��׶���� WATCH����ֹ��δ�ز�ĸ�������ֱ�ӽ���ȯ��ִ�С�

## �������

�ڹ��̸�Ŀ¼��Python3.12 CPU������

```text
python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements-research.txt
python -m unittest discover -s tests -v
node tests/test_worker.mjs
python -m paper.integrations --input validated-session.json --output state/report.json
python -m paper.mining --input one-symbol-history.json --output state/research-factor.json --limit 192
```

������������700����Ч���ߡ������������ļ�ʱ����ʧ�ܣ������Զ����ϳ����顣�ϳ�����ֻ���ڲ��Դ����ڡ�

## ����ƶ˲��

- Cloudflare Workers��״̬����ҳ����Ȩ�븻; REST ֻ�����ӡ��ƶ�ˢ�����ƺͶ�ȡA��ģ���˻���ʵ��ɹ�����ǰ��Ȩ�� `quote:read`��û���µ���֤��
- GitHub Actions�������˹����ֿ��׼ Ubuntu runner ������/�ֶ���֤���������̶�20���ӳ�ʱ���޸���ģ�͡��޴���runner���޻����artifact�ϴ��������ֿ��׼runner������ѣ����вֿ� https://github.com/zhupengcheng0416/a-share-paper �����ߣ��״α�׼Ubuntu������֤�ɹ������м�¼��cloud-research-verification.json���ٷ����ݣ�https://docs.github.com/en/billing/concepts/product-billing/github-actions
- ����PyTorch��Python֧���������治��ֱ������ͨWorkers���С�Workers���ƣ�https://developers.cloudflare.com/workers/platform/limits/
- ������顢�Ʊ��������ڡ���ҵ/��ֵ��ʷ����������飬�������շ����鲹�롣�����г������ʱ������δʵ�⣬��Ԥ��ʱ��ͣ��

## ԭ���ܽ���״̬

��ʵ�֣�˫��Ʊ�ع���ȱʧ�������ء�����ѡ�ɹ��򡢷���Ԥ��/�۶�ģ�顢������Ŀ���о����롢������������;�ƶ�ֻ�����ӡ����ϴ�������ƶ���֤��������

δ��ɣ���ʵȫ�г����������븲��ͳ�ƣ����Բ���/����ز⣻A��T+1/�ǵ�ͣ/����/����������ϣ�EXIT�����ֳɽ�����߶��ˣ��ʼ�outboxͶ�ݣ�ģ�ⶩ��дȨ�޺��Զ��µ�����ʵ�г����������Ķ�ʱ�����𡣵�ǰû���κ�ģ�����ʵ�����ύ��
