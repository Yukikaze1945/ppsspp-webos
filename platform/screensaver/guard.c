/* SPDX-License-Identifier: GPL-3.0-only
 * webOS community adaptation, modified 2026-10-31.
 * Bridge-derived files retain their upstream provenance; see THIRD_PARTY_NOTICES.md.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include "cJSON.h"

/* App-owned, unprivileged helper. Match LG SDL2's timer-reset operation,
 * strictly while this app is foreground and its game heartbeat is fresh.
 * Never remove a timer, change its interval, inject input or wake the screen. */
#define CLIENT "org.ppsspp.webos"
static volatile sig_atomic_t stopping;
static void stop(int sig) {(void)sig;stopping=1;}
static uint64_t now_ms(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000+t.tv_nsec/1000000;}
static void child_lifetime(pid_t parent){prctl(PR_SET_PDEATHSIG,SIGTERM);if(getppid()!=parent)_exit(1);}

static pid_t spawn_call(const char *uri,const char *payload,int *output){
 int fds[2];if(pipe2(fds,O_CLOEXEC)<0)return -1;
 pid_t parent=getpid(),pid=fork();
 if(pid==0){signal(SIGTERM,SIG_DFL);child_lifetime(parent);dup2(fds[1],STDOUT_FILENO);close(fds[0]);close(fds[1]);
  int null=open("/dev/null",O_RDONLY);if(null>=0){dup2(null,STDIN_FILENO);close(null);}
  execl("/usr/bin/timeout","timeout","2","/usr/bin/luna-send-pub","-n","1",uri,payload,(char*)0);
  _exit(127);
 }
 close(fds[1]);if(pid<0){close(fds[0]);return -1;}
 *output=fds[0];return pid;
}
static void call_once(const char *uri,const char *payload,char *buffer,size_t size){
 int fd;pid_t pid=spawn_call(uri,payload,&fd);buffer[0]=0;if(pid<0)return;
 size_t n=0;uint64_t end=now_ms()+2500;
 while(!stopping&&now_ms()<end&&n+1<size){struct pollfd p={fd,POLLIN,0};int r=poll(&p,1,100);if(r<0&&errno==EINTR)continue;if(r<=0)continue;
  ssize_t got=read(fd,buffer+n,size-n-1);if(got<=0)break;n+=(size_t)got;}
 buffer[n]=0;close(fd);if(waitpid(pid,NULL,WNOHANG)==0){kill(pid,SIGTERM);while(waitpid(pid,NULL,0)<0&&errno==EINTR){}}
}
static cJSON *root_call(const char *uri,const char *json){
 /* All callers supply fixed URIs/JSON or a validated decimal timer suffix.
  * No command-line arguments, filenames or game content enter this command. */
 char command[512];
 snprintf(command,sizeof(command),"/usr/bin/timeout 2 /usr/bin/luna-send -n 1 %s '%s'",uri,json);
 cJSON *request=cJSON_CreateObject();cJSON_AddStringToObject(request,"command",command);
 char *payload=cJSON_PrintUnformatted(request),text[4096];
 call_once("luna://org.webosbrew.hbchannel.service/exec",payload,text,sizeof(text));
 cJSON *outer=cJSON_Parse(text),*inner=NULL;
 cJSON *out=outer?cJSON_GetObjectItemCaseSensitive(outer,"stdoutString"):NULL;
 if(cJSON_IsString(out))inner=cJSON_Parse(out->valuestring);
 int ok=inner&&cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(inner,"returnValue"));
 if(!ok){fprintf(stderr,"screensaver RPC failed uri=%s reply=%s\n",uri,text);cJSON_Delete(inner);inner=NULL;}
 cJSON_Delete(outer);cJSON_free(payload);cJSON_Delete(request);return inner;
}
static int reset_timer(uint64_t heartbeat){
 cJSON *timers=root_call("luna://com.webos.service.nop/getTimerInfo","{\"subscribe\":true}");
 if(!timers)return -1;
 char timer_id[64]={0};
 cJSON *item;
 cJSON_ArrayForEach(item,cJSON_GetObjectItemCaseSensitive(timers,"timers")){
  cJSON *type=cJSON_GetObjectItemCaseSensitive(item,"type");
  const char *prefix="[TIMER]ScreenSaver:";
  if(!cJSON_IsString(type)||strncmp(type->valuestring,prefix,strlen(prefix)))continue;
  const char *suffix=type->valuestring+strlen(prefix);char *end;
  long seconds=strtol(suffix,&end,10);
  if(!*suffix||*end||seconds<1||seconds>86400||strspn(suffix,"0123456789")!=strlen(suffix))continue;
  snprintf(timer_id,sizeof(timer_id),"[TIMER]ScreenSaver:%ld",seconds);break;
 }
 cJSON_Delete(timers);
 if(!*timer_id){fprintf(stderr,"screensaver timer not present; no change\n");return 0;}
 /* This is the compositor's actual window list, not SAM's app identity,
  * which can still report PPSSPP while an overlay or Home covers it. */
 cJSON *window=root_call("luna://com.webos.surfacemanager/getForegroundWindowInfo","{}");
 if(!window)return -1;
 cJSON *windows=cJSON_GetObjectItemCaseSensitive(window,"windows");
 int own=cJSON_IsArray(windows)&&cJSON_GetArraySize(windows)>0;
 cJSON_ArrayForEach(item,windows){
  cJSON *id=cJSON_GetObjectItemCaseSensitive(item,"appId");
  if(!cJSON_IsString(id)||strcmp(id->valuestring,CLIENT))own=0;
 }
 cJSON_Delete(window);
 if(!own||stopping||now_ms()-heartbeat>=3000){fprintf(stderr,"screensaver reset skipped: background/overlay/stale heartbeat\n");return 0;}
 char json[128];snprintf(json,sizeof(json),"{\"timerId\":\"%s\",\"option\":\"reset\"}",timer_id);
 cJSON *reply=root_call("luna://com.webos.service.nop/removeNopTimer",json);
 int ok=reply!=NULL;cJSON_Delete(reply);
 fprintf(stderr,"screensaver reset timer=%s accepted=%d monotonic_ms=%llu\n",timer_id,ok,(unsigned long long)now_ms());
 return ok?1:-1;
}
int main(int argc,char **argv){
 (void)argv;if(argc!=1)return 2;
 pid_t parent=getppid();child_lifetime(parent);signal(SIGTERM,stop);signal(SIGINT,stop);signal(SIGPIPE,SIG_IGN);
 setvbuf(stderr,NULL,_IOLBF,0);
 fprintf(stderr,"screensaver timer guard pid=%d parent=%d uid=%d\n",getpid(),parent,geteuid());
 int active=0,failures=0;uint64_t heartbeat=0,last_attempt=0;
 while(!stopping){
  struct pollfd p={STDIN_FILENO,POLLIN,0};int r=poll(&p,1,500);
  if(r<0){if(errno==EINTR)continue;break;}
  if(r>0){char b[64];ssize_t n=read(STDIN_FILENO,b,sizeof(b));if(n<=0)break;
   for(ssize_t i=0;i<n;i++)if(b[i]=='0'||b[i]=='1'){active=b[i]=='1';heartbeat=now_ms();}}
  const uint64_t now=now_ms();int wanted=active&&now-heartbeat<3000;
  if(!wanted){last_attempt=0;continue;}
  if(!last_attempt||now-last_attempt>=20000){
   last_attempt=now;
   if(reset_timer(heartbeat)>=0)failures=0;
   else if(++failures>=3){fprintf(stderr,"screensaver timer unavailable; stopping retries\n");break;}
  }
 }
 /* Nothing to restore: the original timer is still running at its original
  * interval. EOF/parent death simply stops further activity resets. */
 fprintf(stderr,"screensaver timer guard stopped\n");return 0;
}
