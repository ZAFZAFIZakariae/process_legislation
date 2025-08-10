class Theme{
  constructor(){this.key='theme';this.pref=localStorage.getItem(this.key)||'dark';document.documentElement.dataset.theme=this.pref;}
  toggle(){this.pref=this.pref==='dark'?'light':'dark';document.documentElement.dataset.theme=this.pref;localStorage.setItem(this.key,this.pref);Toast.show(`Switched to ${this.pref} mode`,'info');}
}
class Palette{
  constructor(actions){this.el=document.getElementById('palette');this.input=this.el.querySelector('input');this.list=this.el.querySelector('ul');this.actions=actions;this.index=0;this.bind();}
  bind(){document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();this.open();}});this.input.addEventListener('input',()=>this.render());this.el.addEventListener('keydown',e=>{if(e.key==='Escape')this.close();if(e.key==='ArrowDown'){this.index=Math.min(this.index+1,this.filtered.length-1);this.highlight();}if(e.key==='ArrowUp'){this.index=Math.max(this.index-1,0);this.highlight();}if(e.key==='Enter'){this.select();}});}
  open(){this.el.classList.remove('hidden');this.input.value='';this.render();this.input.focus();}
  close(){this.el.classList.add('hidden');}
  render(){const q=this.input.value.toLowerCase();this.filtered=this.actions.filter(a=>a.label.toLowerCase().includes(q));this.list.innerHTML='';this.filtered.forEach((a,i)=>{const li=document.createElement('li');li.textContent=a.label;if(i===0){li.classList.add('active');}this.list.appendChild(li);});this.index=0;}
  highlight(){[...this.list.children].forEach((li,i)=>li.classList.toggle('active',i===this.index));}
  select(){const act=this.filtered[this.index];if(act){act.run();this.close();}}
}
class Toast{
  static show(msg,type='info',ms=3000){const wrap=document.getElementById('toasts');const t=document.createElement('div');t.className=`toast ${type}`;t.textContent=msg;wrap.appendChild(t);setTimeout(()=>t.remove(),ms);}
}
class Sidebar{
  constructor(){this.el=document.querySelector('.sidebar');this.key='sidebar';const saved=localStorage.getItem(this.key);if(saved==='true'){this.collapse(true);}this.el.querySelector('.sidebar-toggle').addEventListener('click',()=>this.collapse());}
  collapse(force){const collapsed=force!==undefined?force:this.el.dataset.collapsed!=='true';this.el.dataset.collapsed=collapsed;localStorage.setItem(this.key,collapsed);}
}
document.addEventListener('DOMContentLoaded',()=>{
  const theme=new Theme();
  const actions=[
    {label:'Go to Corpus',run:()=>location.href='/corpus'},
    {label:'Toggle theme',run:()=>theme.toggle()}
  ];
  const palette=new Palette(actions);
  new Sidebar();
  document.querySelector('[data-action="theme-toggle"]').addEventListener('click',()=>theme.toggle());
  const open=document.querySelector('[data-action="open-palette"]');
  if(open){open.addEventListener('click',()=>palette.open());}
});
