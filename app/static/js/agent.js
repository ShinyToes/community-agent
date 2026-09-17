(() => {
  'use strict';
  const root = document.getElementById('agentRoot'), csrf = root.dataset.csrf;
  const $ = id => document.getElementById(id);
  const storageKey = 'student-agent-conversation-' + root.dataset.user;
  let conversation = localStorage.getItem(storageKey), selectedBatch = null, poll = null;
  const labels = {student_id:'学号', name:'姓名', daily_score:'平时成绩', midterm_score:'期中成绩',
    final_score:'期末成绩', makeup_score:'补考成绩', total_score:'总评', gpa:'绩点', course_name:'课程',
    course_code:'课程代码', offering_id:'开课编号', academic_year:'学年', semester:'学期',
    status:'状态', major_id:'专业编号', class_id:'班级编号', gender:'性别', phone:'电话', email:'邮箱',
    enrollment_year:'入学年份', education_length:'学制', education_level:'培养层次', credits:'学分',
    hours:'学时', course_type:'课程性质', teacher_id:'教师编号', max_students:'容量',
    title:'标题', type:'类型', rp_date:'日期', date:'日期', level:'级别', description:'说明', remaining:'剩余名额',
    major_name:'专业', class_name:'班级', teacher_name:'教师', birth_date:'出生日期', schedule:'上课时间', classroom:'教室'};
  const states={queued:'待识别',parsing:'识别中',ready:'待确认',needs_review:'需要修正',failed:'识别失败',committed:'已入库',cancelled:'已取消'};
  const actions={insert:'新增',update:'更新',unchanged:'无变化'};
  function el(tag, text, cls) {
    const node = document.createElement(tag); if (text !== undefined) node.textContent = String(text);
    if (cls) node.className = cls; return node;
  }
  function notice(text, error=false) {
    $('notice').textContent=text; $('notice').className='alert '+(error?'alert-danger':'alert-info');
  }
  async function api(path, method='GET', body) {
    const opts={method,headers:{'X-CSRFToken':csrf}};
    if(body instanceof FormData) opts.body=body;
    else if(body!==undefined) {opts.body=JSON.stringify(body);opts.headers['Content-Type']='application/json';}
    const response=await fetch(path,opts);
    if(response.redirected) throw Error('会话已失效，请重新登录');
    let value;try{value=await response.json();}catch{throw Error('请求失败，请刷新登录状态或检查服务日志');}
    if(!response.ok) throw Error(value.error || '请求失败');
    return value;
  }
  function button(text, action, cls='btn btn-sm btn-outline-primary me-2') {
    const b=el('button',text,cls);b.type='button';
    b.onclick=async()=>{b.disabled=true;try{await action();}catch(e){notice(e.message,true);}finally{b.disabled=false;}};
    return b;
  }
  function table(rows) {
    const wrap=el('div',undefined,'table-responsive'), t=el('table',undefined,'table table-sm table-bordered text-nowrap');
    if(!rows.length){wrap.append(el('p','按当前条件没有查到记录'));return wrap;}
    const keys=Object.keys(rows[0]), head=el('tr');keys.forEach(k=>head.append(el('th',labels[k]||k)));t.append(head);
    for(const row of rows){const tr=el('tr');keys.forEach(k=>tr.append(el('td',row[k]??'未填写')));t.append(tr);}
    wrap.append(t);return wrap;
  }
  function diff(plan) {
    const before=plan.before||{}, after=plan.after||{}, rows=[];
    for(const k of new Set([...Object.keys(before),...Object.keys(after)])){
      if(String(before[k])!==String(after[k]))rows.push({'字段':labels[k]||k,'原值':before[k]??'无','拟写入':after[k]??'空'});
    }
    return table(rows);
  }
  function resultView(result, parent) {
    if(result.error){parent.append(el('p',result.error,'text-danger'));return;}
    if(result.draft_id){
      const card=el('div',undefined,'border rounded p-2 mb-3');
      card.append(el('strong','待确认修改'),el('p','原因：'+result.reason),diff(result));
      card.append(button('确认修改',async()=>{
        if(!confirm('确认将上面展示的差异写入数据库？'))return;
        const r=await api('/agent/drafts/'+result.draft_id+'/confirm','POST',{});
        notice(r.message);card.replaceChildren(el('p',r.message,'text-success'));
      }),button('取消',async()=>{await api('/agent/drafts/'+result.draft_id+'/cancel','POST',{});card.textContent='已取消';}));
      parent.append(card);return;
    }
    if(result.rows){
      parent.append(el('p','条件：'+JSON.stringify(result.filters||{})+'；总数 '+result.total+'；第 '+result.page+' 页','small text-muted'),table(result.rows));
    }
  }
  function message(role,text,results=[]) {
    const block=el('div',undefined,'border-bottom py-2');
    block.append(el('strong',role==='user'?'你':'助手'),el('p',text));
    results.forEach(r=>resultView(r,block));$('messages').append(block);
  }
  async function ensureConversation() {
    if(!conversation){const c=await api('/agent/conversations','POST',{});conversation=c.id;localStorage.setItem(storageKey,conversation);}
  }
  $('newConversation').onclick=()=>{conversation=null;localStorage.removeItem(storageKey);$('messages').replaceChildren();notice('已开始新会话');};
  $('chatForm').onsubmit=async event=>{
    event.preventDefault();const text=$('question').value.trim();if(!text)return;
    const send=event.target.querySelector('button');send.disabled=true;
    try{await ensureConversation();message('user',text);$('question').value='';
      const r=await api('/agent/conversations/'+conversation+'/messages','POST',{text});
      message('assistant',r.answer,r.results);notice('已完成；查询结果与修改草稿见对话区');
    }catch(e){notice(e.message,true);}finally{send.disabled=false;}
  };
  $('directQuery').onclick=async()=>{
    const kind=$('queryKind').value,filters={};if($('queryStudent').value)filters.student_id=$('queryStudent').value;
    if($('queryOffering').value && ['grades','courses'].includes(kind))filters.offering_id=$('queryOffering').value;
    try{const r=await api('/agent/query','POST',{kind,filters});message('assistant','数据库查询结果',[r]);}catch(e){notice(e.message,true);}
  };
  async function refresh() {
    const list=await api('/imports');$('batches').replaceChildren();
    list.batches.forEach(b=>$('batches').append(button(b.name+' · '+(states[b.status]||b.status),()=>showBatch(b.id),'btn btn-sm btn-outline-secondary mb-2 me-2')));
  }
  async function showBatch(id) {
    selectedBatch=id;if(poll)clearTimeout(poll);
    const b=await api('/imports/'+id), area=$('batchDetail');area.replaceChildren();
    area.append(el('h5',b.name),el('p','状态：'+(states[b.status]||b.status)+' · 版本 '+b.version,'text-muted'));
    const original=el('a','查看原始文档');original.href='/imports/'+id+'/document';area.append(original);
    if(b.error)area.append(el('p',b.error,'text-danger'));
    if(['queued','parsing'].includes(b.status)){
      area.append(el('p','后台正在处理。请确保导入 Worker 已启动。'));
      poll=setTimeout(()=>showBatch(id).catch(e=>notice(e.message,true)),3000);
    }
    if(b.status==='failed')area.append(button('按当前目标重试',async()=>{
      const options={...b.options};if($('sheet').value)options.sheet=$('sheet').value;
      if($('offering').value)options.offering_id=$('offering').value;
      await api('/imports/'+id+'/retry','POST',{options});await showBatch(id);
    }));
    if(b.receipt)area.append(el('p','本次已入库：'+Object.entries(b.receipt.counts).map(([k,v])=>(actions[k]||'排除')+' '+v+' 行').join('，')));
    if(/\.(pdf|png|jpe?g|docx)$/i.test(b.name))area.append(el('p','识别值可能有误，请逐行对照原始文档，特别核对学号和数字。','text-warning'));
    const editable=['ready','needs_review'].includes(b.status);
    if(editable){
      const errors=b.rows.filter(r=>r.error&&!r.excluded).length;
      area.append(el('p',b.rows.length+' 行，未解决错误 '+errors+' 行，已排除 '+b.rows.filter(r=>r.excluded).length+' 行'));
      const commit=button('确认导入本次预览',async()=>{
        if(!confirm('确认导入本次预览中未排除的行？'))return;
        await api('/imports/'+id+'/commit','POST',{version:b.version});await showBatch(id);await refresh();
      },'btn btn-success me-2');commit.disabled=b.status!=='ready';area.append(commit);
      area.append(button('重新校验',async()=>{await api('/imports/'+id+'/validate','POST',{version:b.version});await showBatch(id);}));
    }
    if(!['cancelled','committed'].includes(b.status))area.append(button('取消批次',async()=>{await api('/imports/'+id+'/cancel','POST',{});await showBatch(id);await refresh();}));
    for(const row of b.rows){
      const detail=el('details',undefined,'border rounded p-2 mt-2');
      detail.append(el('summary','第 '+row.source.row+' 行 · '+(row.error||actions[row.plan?.action]||'已排除')));
      detail.append(el('p',row.source.page?'来源：第 '+row.source.page+' 页':'来源：'+row.source.section+'，第 '+row.source.row+' 行','small'));
      if(row.source.excerpt)detail.append(el('pre',row.source.excerpt,'small'));
      detail.append(el('p','原始字段'),table([row.raw]));
      if(row.plan)detail.append(diff(row.plan));
      if(row.error)detail.append(el('p',row.error,'text-danger'));
      if(editable){
        const inputs={};
        for(const key of b.profile_fields){
          const value=row.candidate[key];
          const label=el('label',labels[key]||key,'form-label'),input=el('input');input.className='form-control form-control-sm mb-2';input.value=value??'';
          detail.append(label,input);inputs[key]=input;
        }
        const excluded=el('input'),allow=el('input');excluded.type=allow.type='checkbox';excluded.checked=row.excluded;allow.checked=row.allow_update;
        const excludeLabel=el('label',undefined,'d-block'),allowLabel=el('label',undefined,'d-block');
        excludeLabel.append(excluded,document.createTextNode(' 排除此行'));allowLabel.append(allow,document.createTextNode(' 已核对差异，允许更新已有记录'));
        detail.append(excludeLabel,allowLabel,button('保存修正并校验',async()=>{
          const candidate=Object.fromEntries(Object.entries(inputs).map(([k,input])=>[k,input.value]));
          await api('/imports/'+id+'/rows/'+row.id,'PATCH',{version:b.version,candidate,excluded:excluded.checked,allow_update:allow.checked});
          await showBatch(id);
        }));
      }
      area.append(detail);
    }
  }
  if($('uploadForm')){
    $('uploadForm').onsubmit=async event=>{
      event.preventDefault();const form=new FormData(event.target),options={};
      if($('sheet').value)options.sheet=$('sheet').value;if($('offering').value)options.offering_id=$('offering').value;
      form.set('options',JSON.stringify(options));const b=event.target.querySelector('button');b.disabled=true;
      try{const batch=await api('/imports','POST',form);await refresh();await showBatch(batch.id);notice('文件已进入待识别队列，尚未写入业务数据');}catch(e){notice(e.message,true);}finally{b.disabled=false;}
    };
    $('refreshBatches').onclick=()=>refresh().catch(e=>notice(e.message,true));refresh().catch(e=>notice(e.message,true));
  }
  $('loadChanges').onclick=async()=>{
    try{const r=await api('/agent/changes');$('changes').replaceChildren();
      for(const change of r.events){const d=el('details',undefined,'border p-2 mb-2');d.append(el('summary',change.created_at+' · '+change.source_type+' · '+change.entity_id),diff(change));
        if(change.batch_id){const a=el('a','查看来源批次');a.href='#';a.onclick=e=>{e.preventDefault();showBatch(change.batch_id).catch(err=>notice(err.message,true));};d.append(a);}
        $('changes').append(d);}
    }catch(e){notice(e.message,true);}
  };
  if(conversation)api('/agent/conversations/'+conversation).then(c=>c.messages.forEach(m=>message(m.role,m.content,m.result?.results||[]))).catch(()=>{
    conversation=null;localStorage.removeItem(storageKey);
  });
})();
