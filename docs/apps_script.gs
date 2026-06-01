const SHEET_ID = '1jTzV58J1luR9u2qNIVamNw0fd8R1ncHlYGz9nVxGMGM';
const SECRET   = 'monazam2025secret';

function doGet(e) {
  const out = ContentService.createTextOutput();
  out.setMimeType(ContentService.MimeType.JSON);
  try {
    if (e.parameter.key !== SECRET) {
      out.setContent(JSON.stringify({ok:false,error:'Unauthorized'})); return out;
    }
    const action = e.parameter.action || '';
    let data;
    if      (action==='get_tasks')       data = getTasks();
    else if (action==='add_task')        data = addTask(e.parameter);
    else if (action==='edit_task')       data = editTask(e.parameter);
    else if (action==='complete_task')   data = completeTask(+e.parameter.id);
    else if (action==='delete_task')     data = deleteTask(+e.parameter.id);
    else if (action==='get_habit_list')  data = getHabitList();
    else if (action==='add_habit')       data = addHabit(e.parameter.name);
    else if (action==='get_habit_week')  data = getHabitWeek(e.parameter.dates);
    else if (action==='get_habit_log')   data = getHabitLog(+e.parameter.year, +e.parameter.month);
    else if (action==='toggle_habit')    data = toggleHabit(e.parameter.habit_name, e.parameter.date);
    else if (action==='get_users')       data = getUsers();
    else data = null;
    out.setContent(JSON.stringify({ok:true,data}));
  } catch(err) {
    out.setContent(JSON.stringify({ok:false,error:err.message}));
  }
  return out;
}

// ── Jalali helpers ────────────────────────────────────────────────────
function jalaliToGregorian(jy,jm,jd){
  jy=+jy;jm=+jm;jd=+jd;
  const jdm=[0,31,31,31,31,31,31,30,30,30,30,30,29];
  let gy=jy<=979?1600:1976; jy-=jy<=979?560:1376;
  let days=(365*jy)+Math.floor(jy/33)*8+Math.floor((jy%33+3)/4)+(78+jd);
  for(let i=0;i<jm-1;i++)days+=jdm[i+1];
  if(jy>1&&(jy-1)%33<6&&(jy-1)%33>0)days++;
  let gd=days-29;
  const g4=Math.floor(gd/1461),gr=gd%1461;
  gd=gr<366?gr+366:gr;
  gy+=4*g4+Math.floor((gd-1)/365.25);
  const gml=[0,31,28,31,30,31,30,31,31,30,31,30,31];
  const leap=(gy%4===0&&gy%100!==0)||(gy%400===0);
  if(leap)gml[2]=29;
  let gm2=1;gd=Math.ceil((gd-1)%365.25);
  while(gd>gml[gm2]){gd-=gml[gm2];gm2++;}
  return new Date(gy,gm2-1,gd);
}

function toJalali(d){
  const gy=d.getFullYear(),gm=d.getMonth()+1,gd=d.getDate();
  let jy=gy-621,jm,jday;
  const g_d=[0,31,59,90,120,151,181,212,243,273,304,334];
  let g_d_no=365*(gy-1)+Math.floor((gy-1)/4)-Math.floor((gy-1)/100)+Math.floor((gy-1)/400)+g_d[gm-1]+gd;
  if(gm>2&&((gy%4===0&&gy%100!==0)||(gy%400===0)))g_d_no++;
  const j_d_no=g_d_no-79;
  const j_np=Math.floor(j_d_no/12053);jy+=33*j_np;
  const j_d_no2=j_d_no%12053;
  jy+=4*Math.floor(j_d_no2/1461);
  const j_d_no3=j_d_no2%1461;
  if(j_d_no3>=366){jy+=Math.floor((j_d_no3-1)/365);jday=(j_d_no3-1)%365;}else{jday=j_d_no3;}
  if(jday<186){jm=1+Math.floor(jday/31);return[jy,jm,jday%31+1];}
  jm=7+Math.floor((jday-186)/30);return[jy,jm,(jday-186)%30+1];
}

function pad(n){return String(n).padStart(2,'0');}
function isoDate(d){return Utilities.formatDate(d,'Asia/Tehran','yyyy-MM-dd');}
function isoNow(){return Utilities.formatDate(new Date(),'Asia/Tehran','yyyy-MM-dd HH:mm');}

function parseJalali(s){
  if(!s)return null;
  const p=s.replace(/-/g,'/').split('/');
  if(p.length!==3)return null;
  try{return jalaliToGregorian(+p[0],+p[1],+p[2]);}catch(e){return null;}
}

function gregToJalaliStr(gDl){
  if(!gDl)return'';
  try{const d=new Date(gDl);const j=toJalali(d);return`${j[0]}/${pad(j[1])}/${pad(j[2])}`;}
  catch(e){return gDl;}
}

// ── Sheet helper ──────────────────────────────────────────────────────
function ws(name){return SpreadsheetApp.openById(SHEET_ID).getSheetByName(name);}

// ── Tasks ─────────────────────────────────────────────────────────────
// Columns: id(0) title(1) deadline(2) assigned_to(3) status(4) priority(5)
//          created_at(6) reminder_at(7) created_by_user_id(8) assigned_user_id(9) reminder_sent(10)
function rowToTask(r){
  const dg = String(r[2]||'');
  return {
    id:                 +r[0],
    title:              String(r[1]||''),
    deadline:           gregToJalaliStr(dg),
    deadline_greg:      dg,
    assigned_to:        String(r[3]||''),
    status:             String(r[4]||'pending'),
    priority:           String(r[5]||'medium'),
    reminder_at:        String(r[7]||''),
    created_by_user_id: String(r[8]||''),
    assigned_user_id:   String(r[9]||''),
  };
}

function getTasks(){
  const rows = ws('tasks').getDataRange().getValues().slice(1);
  return rows.filter(r => r[0]!=='' && r[0]!=='id').map(rowToTask);
}

function addTask(p){
  const w = ws('tasks');
  const newId = w.getLastRow();
  let gDl = '';
  if(p.deadline){const d=parseJalali(p.deadline);if(d)gDl=isoDate(d);}
  // reminder_at = deadline + reminder_time if both set
  let reminderAt = '';
  if(p.reminder_time && gDl) reminderAt = gDl + ' ' + p.reminder_time;
  w.appendRow([
    newId, p.title||'', gDl, p.assigned_to||'', 'pending', 'medium', isoNow(),
    reminderAt, p.created_by_user_id||'', p.assigned_user_id||'', ''
  ]);
  return {
    id: newId, title: p.title||'',
    deadline: gregToJalaliStr(gDl)||p.deadline||'', deadline_greg: gDl,
    assigned_to: p.assigned_to||'', status:'pending', priority:'medium',
    reminder_at: reminderAt, created_by_user_id: p.created_by_user_id||'',
    assigned_user_id: p.assigned_user_id||''
  };
}

function editTask(p){
  const w = ws('tasks');
  const rows = w.getDataRange().getValues();
  const id = +p.id;
  for(let i=1;i<rows.length;i++){
    if(+rows[i][0]===id){
      let gDl = '';
      if(p.deadline){const d=parseJalali(p.deadline);if(d)gDl=isoDate(d);}
      let reminderAt = '';
      if(p.reminder_time && gDl) reminderAt = gDl + ' ' + p.reminder_time;
      // Update B:D (title, deadline, assigned_to)
      w.getRange(i+1,2,1,3).setValues([[p.title||'', gDl, p.assigned_to||'']]);
      // Update H:K (reminder_at, created_by_user_id, assigned_user_id, reminder_sent)
      w.getRange(i+1,8,1,4).setValues([[reminderAt, p.created_by_user_id||rows[i][8]||'', p.assigned_user_id||'', '']]);
      return {ok:true, deadline_greg: gDl, reminder_at: reminderAt};
    }
  }
  return {ok:false};
}

function completeTask(id){
  const w=ws('tasks');const rows=w.getDataRange().getValues();
  for(let i=1;i<rows.length;i++){if(+rows[i][0]===id){w.getRange(i+1,5).setValue('done');return true;}}
  return false;
}

function deleteTask(id){
  const w=ws('tasks');const rows=w.getDataRange().getValues();
  for(let i=1;i<rows.length;i++){if(+rows[i][0]===id){w.deleteRow(i+1);return true;}}
  return false;
}

// ── Users ─────────────────────────────────────────────────────────────
function getUsers(){
  try{
    const rows = ws('users').getDataRange().getValues().slice(1);
    return rows.filter(r=>r[0]!=='').map(r=>({id:String(r[0]),name:String(r[1]||''),username:String(r[2]||'')}));
  }catch(e){return[];}
}

// ── Habits ────────────────────────────────────────────────────────────
function getHabitList(){
  const rows=ws('habit_list').getDataRange().getValues().slice(1);
  return rows.filter(r=>String(r[1]).toUpperCase()==='TRUE').map(r=>r[0]);
}

function addHabit(name){
  if(!name)return{ok:false};
  ws('habit_list').appendRow([name,'TRUE']);
  return{ok:true,name};
}

function getHabitWeek(datesStr){
  // datesStr: comma-separated ISO dates, e.g. "2026-05-30,2026-05-31,...,2026-06-05"
  const dateArr = (datesStr||'').split(',').filter(Boolean);
  const rows = ws('habits').getDataRange().getValues().slice(1);
  const result = {};
  rows.forEach(r=>{
    const d=String(r[0]),h=String(r[1]),done=String(r[2]).toUpperCase();
    if(dateArr.includes(d)&&done==='TRUE'){
      if(!result[d])result[d]=[];
      result[d].push(h);
    }
  });
  return result;
}

function getHabitLog(jy,jm){
  const nd = jm<=6?31:jm<=11?30:29;
  const firstG = jalaliToGregorian(jy,jm,1);
  const lastG  = jalaliToGregorian(jy,jm,nd);
  const firstIso = isoDate(firstG);
  const lastIso  = isoDate(lastG);
  const rows = ws('habits').getDataRange().getValues().slice(1);
  const result = {};
  rows.forEach(r=>{
    const d=String(r[0]),h=String(r[1]),done=String(r[2]).toUpperCase();
    if(d>=firstIso&&d<=lastIso&&done==='TRUE'){
      if(!result[d])result[d]=[];
      result[d].push(h);
    }
  });
  return result;
}

function toggleHabit(habitName,dateIso){
  const w=ws('habits');
  const rows=w.getDataRange().getValues();
  for(let i=1;i<rows.length;i++){
    if(rows[i][0]===dateIso&&rows[i][1]===habitName){
      const cur=String(rows[i][2]).toUpperCase();
      w.getRange(i+1,3).setValue(cur==='TRUE'?'FALSE':'TRUE');
      return cur!=='TRUE';
    }
  }
  w.appendRow([dateIso,habitName,'TRUE']);
  return true;
}
