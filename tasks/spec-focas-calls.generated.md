# tasks/spec-focas-calls.generated.md

_Auto-extracted from `C:\Fanuc\FwLib64-runtime\Fwlib64.h` by `scripts/extract_focas_signatures.py`._
_Verbatim text — review, then merge relevant sections into `tasks/spec-focas-calls.md`._

## Summary

- Found: 30 / 39
- Missing: 9

| Function | Status |
|---|---|
| `cnc_allclibhndl3` | found |
| `cnc_freelibhndl` | found |
| `cnc_settimeout` | found |
| `cnc_sysinfo` | found |
| `cnc_sysinfo_ex` | found |
| `cnc_statinfo` | found |
| `cnc_statinfo2` | found |
| `cnc_modal` | found |
| `cnc_rdtofs` | found |
| `cnc_rdtofsr` | found |
| `cnc_rdtofsinfo` | found |
| `cnc_wrtofs` | found |
| `cnc_rdmagazine` | found |
| `cnc_rdngrp` | found |
| `cnc_rdgrpid` | found |
| `cnc_rdgrpid2` | found |
| `cnc_rdusegrpid` | found |
| `cnc_rd1tlifedata` | found |
| `cnc_rdalmmsg` | found |
| `cnc_rdalmmsg2` | found |
| `cnc_rdtdiseltool` | found |
| `cnc_rdtltool` | found |
| `cnc_rdtltoolnum` | **NOT FOUND** |
| `cnc_rdtldata` | found |
| `cnc_rdtoolinfo` | found |
| `cnc_rdactivetool` | **NOT FOUND** |
| `cnc_rdmacro` | found |
| `cnc_rdmacror` | found |
| `cnc_rdtllife` | **NOT FOUND** |
| `cnc_rdtlinfo` | found |
| `cnc_rdcurmgr` | **NOT FOUND** |
| `cnc_rdcurpot` | **NOT FOUND** |
| `cnc_rdpotinfo` | **NOT FOUND** |
| `cnc_rdmagsts` | **NOT FOUND** |
| `cnc_rdspmaint` | **NOT FOUND** |
| `cnc_rdspload` | found |
| `cnc_rdmgrptool` | **NOT FOUND** |
| `pmc_rdpmcrng` | found |
| `pmc_rdpmcinfo` | found |

## `cnc_allclibhndl3`

Signature (verbatim):

```c
/*---------------------*/
/* Ethernet connection */
/*---------------------*/

/* allocate library handle 3 */
FWLIBAPI short WINAPI cnc_allclibhndl3( const char *, unsigned short, long, unsigned short * );
```

No referenced user-defined types in arg list.

## `cnc_freelibhndl`

Signature (verbatim):

```c
/* free library handle */
FWLIBAPI short WINAPI cnc_freelibhndl( unsigned short ) ;
```

No referenced user-defined types in arg list.

## `cnc_settimeout`

Signature (verbatim):

```c
/* set timeout for socket */
FWLIBAPI short WINAPI cnc_settimeout( unsigned short, long );
```

No referenced user-defined types in arg list.

## `cnc_sysinfo`

Signature (verbatim):

```c
/*-------------*/
/* CNC: Others */
/*-------------*/

/* read CNC system information */
FWLIBAPI short WINAPI cnc_sysinfo( unsigned short, ODBSYS * ) ;
```

Referenced struct/type names: `ODBSYS`

- `ODBSYS`:

```c
typedef struct odbsys {
    short   addinfo ;       /* additional information  */
    short   max_axis ;      /* maximum axis number */
    char    cnc_type[2] ;   /* cnc type <ascii char> */
    char    mt_type[2] ;    /* M/T/TT <ascii char> */
    char    series[4] ;     /* series NO. <ascii char> */
    char    version[4] ;    /* version NO.<ascii char> */
    char    axes[2] ;       /* axis number<ascii char> */
} ODBSYS ;
```

## `cnc_sysinfo_ex`

Signature (verbatim):

```c
/* read CNC system path information */
FWLIBAPI short WINAPI cnc_sysinfo_ex( unsigned short, ODBSYSEX * ) ;
```

Referenced struct/type names: `ODBSYSEX`

- `ODBSYSEX`:

```c
typedef struct odbsysex {
    short max_axis;       /* maximum axis number */
    short max_spdl;       /*  */
    short max_path;       /*  */
    short max_mchn;       /*  */
    short ctrl_axis;      /*  */
    short ctrl_srvo;      /*  */
    short ctrl_spdl;      /*  */
    short ctrl_path;      /*  */
    short ctrl_mchn;      /*  */
    short addinfo ;       /* additional information	*/
    short reserved[2];    /* reserve		 		*/
    struct {
        short system;     /* M/T/TT <ascii char> */
        short group;      /*  */
        short attrib;     /*  */
        short ctrl_axis;  /*  */
        short ctrl_srvo;  /*  */
        short ctrl_spdl;  /*  */
        short mchn_no;    /*  */
        short reserved;
    } path[MAX_CNCPATH] ;
} ODBSYSEX ;
```

## `cnc_statinfo`

Signature (verbatim):

```c
/* read CNC status information */
FWLIBAPI short WINAPI cnc_statinfo( unsigned short, ODBST * ) ;
```

Referenced struct/type names: `ODBST`

- `ODBST`:

```c
typedef struct odbst {
    short dummy[2];     /* dummy                    */
    short aut;          /* selected automatic mode  */
    short manual;       /* selected manual mode     */
    short run;          /* running status           */
    short edit;         /* editting status          */
    short motion;       /* axis, dwell status       */
    short mstb;         /* m, s, t, b status        */
    short emergency;    /* emergency stop status    */
    short write;        /* writting status          */
    short labelskip;    /* label skip status        */
    short alarm;        /* alarm status             */
    short warning;      /* warning status           */
    short battery;      /* battery status           */
} ODBST ;
```

## `cnc_statinfo2`

Signature (verbatim):

```c
/* read CNC status information */
FWLIBAPI short WINAPI cnc_statinfo2( unsigned short, ODBST2 * ) ;
```

Referenced struct/type names: `ODBST2`

- `ODBST2`:

```c
typedef struct odbst2 {
    short   hdck ;      /* handl retrace status */
    short   tmmode ;    /* T/M mode */
    short   aut ;       /* selected automatic mode */
    short   run ;       /* running status */
    short   motion ;    /* axis, dwell status */
    short   mstb ;      /* m, s, t, b status */
    short   emergency ; /* emergency stop status */
    short   alarm ;     /* alarm status */
    short   edit ;      /* editting status */
    short   warning ;   /* warning status */
    short   o3dchk;     /* o3dchk status */
    short   ext_opt;    /* option */
    short   restart;    /* State of edit when SBK */
} ODBST2 ;
```

## `cnc_modal`

Signature (verbatim):

```c
/* read modal data */
FWLIBAPI short WINAPI cnc_modal( unsigned short, short, short, ODBMDL * ) ;
```

Referenced struct/type names: `ODBMDL`

- `ODBMDL`:

```c
typedef struct odbmdl {
    short   datano;
    short   type;
    union {
        char    g_data;
        char    g_rdata[12];
        char    g_1shot;
        struct {
            long    aux_data;
            char    flag1;
            char    flag2;
        }aux;
        struct {
            long    aux_data;
            char    flag1;
            char    flag2;
        }raux1[25];
    }modal;
} ODBMDL ;
```

## `cnc_rdtofs`

Signature (verbatim):

```c
/*---------------------------*/
/* CNC: NC file data related */
/*---------------------------*/

/* read tool offset value */
FWLIBAPI short WINAPI cnc_rdtofs( unsigned short, short, short, short, ODBTOFS * ) ;
```

Referenced struct/type names: `ODBTOFS`

- `ODBTOFS`:

```c
typedef struct odbtofs {
    short   datano ;    /* data number */
    short   type ;      /* data type */
    long    data ;      /* data */
} ODBTOFS ;
```

## `cnc_rdtofsr`

Signature (verbatim):

```c
/* read tool offset value(area specified) */
FWLIBAPI short WINAPI cnc_rdtofsr( unsigned short, short, short, short, short, IODBTO * ) ;
```

Referenced struct/type names: `IODBTO`

- `IODBTO`:

```c
typedef struct iodbto {
    short   datano_s ;  /* start offset number */
    short   type ;      /* offset type */
    short   datano_e ;  /* end offset number */
    union {
        long    m_ofs[5] ;      /* M Each */
        long    m_ofs_a[5] ;    /* M-A All */
        long    m_ofs_b[10] ;   /* M-B All */
        long    m_ofs_c[20] ;   /* M-C All */
        struct  {
            short   tip ;
            long    data[1] ;
        } m_ofs_at[5] ;         /* M-A All with tip */
        struct  {
            short   tip ;
            long    data[2] ;
        } m_ofs_bt[5] ;         /* M-A All with tip  */
        struct  {
            short   tip ;
            long    data[4] ;
        } m_ofs_ct[5] ;         /* M-A All with tip  */
        short   t_tip[5] ;      /* T Each, 2-byte */
        long    t_ofs[5] ;      /* T Each, 4-byte */
        struct  {
            short   tip ;
            long    data[4] ;
        } t_ofs_a[5] ;          /* T-A All */
        struct {
            short   tip ;
            long    data[8] ;
        } t_ofs_b[5] ;          /* T-B All */
        long    t_ofs_2g[15];   /* T-2nd geometry */
        long    m_ofs_cnr[10];  /* M-CornerR */
        struct  {
                long    data[2];
        } t_ofs_ex[5];		     /* T-Ex-Ofs */
    } u ;   /* In case that the number of data is 5 */
} IODBTO ;
```

## `cnc_rdtofsinfo`

Signature (verbatim):

```c
/* read tool offset information */
FWLIBAPI short WINAPI cnc_rdtofsinfo( unsigned short, ODBTLINF * ) ;
```

Referenced struct/type names: `ODBTLINF`

- `ODBTLINF`:

```c
typedef struct odbtlinf {
    short   ofs_type;
    short   use_no;
} ODBTLINF;
```

## `cnc_wrtofs`

Signature (verbatim):

```c
/* write tool offset value */
FWLIBAPI short WINAPI cnc_wrtofs( unsigned short, short, short, short, long ) ;
```

No referenced user-defined types in arg list.

## `cnc_rdmagazine`

Signature (verbatim):

```c
/* read magazine management data */
FWLIBAPI short WINAPI cnc_rdmagazine( unsigned short, short *, IODBTLMAG * ) ;
```

Referenced struct/type names: `IODBTLMAG`

- `IODBTLMAG`:

```c
typedef struct  iodbtlmag {
    short magazine;
    short pot;
    short tool_index;
} IODBTLMAG;
```

## `cnc_rdngrp`

Signature (verbatim):

```c
/* read tool life management data(number of tool groups) */
FWLIBAPI short WINAPI cnc_rdngrp( unsigned short, ODBTLIFE2 * ) ;
```

Referenced struct/type names: `ODBTLIFE2`

- `ODBTLIFE2`:

```c
typedef struct odbtlife2 {
    short   dummy[2] ;  /* dummy */
    long    data ;      /* data */
} ODBTLIFE2 ;
```

## `cnc_rdgrpid`

Signature (verbatim):

```c
/*----------------------------------------*/
/* CNC: Tool life management data related */
/*----------------------------------------*/

/* read tool life management data(tool group number) */
FWLIBAPI short WINAPI cnc_rdgrpid( unsigned short, short, ODBTLIFE1 * ) ;
```

Referenced struct/type names: `ODBTLIFE1`

- `ODBTLIFE1`:

```c
typedef struct odbtlife1 {
    short   dummy ; /* dummy */
    short   type ;  /* data type */
    long    data ;  /* data */
} ODBTLIFE1 ;
```

## `cnc_rdgrpid2`

Signature (verbatim):

```c
/* read tool life management data(tool group number) 2 */
FWLIBAPI short WINAPI cnc_rdgrpid2( unsigned short, long, ODBTLIFE5 * ) ;
```

Referenced struct/type names: `ODBTLIFE5`

- `ODBTLIFE5`:

```c
typedef struct odbtlife5 {
    long    dummy ; /* dummy */
    long    type ;  /* data type */
    long    data ;  /* data */
} ODBTLIFE5 ;
```

## `cnc_rdusegrpid`

Signature (verbatim):

```c
/* read tool life management data(used tool group number) */
FWLIBAPI short WINAPI cnc_rdusegrpid( unsigned short, ODBUSEGR * ) ;
```

Referenced struct/type names: `ODBUSEGR`

- `ODBUSEGR`:

```c
typedef struct odbusegr {
    short   datano; /* dummy */
    short   type;   /* dummy */
    long    next;   /* next use group number */
    long    use;    /* using group number */
    long    slct;   /* selecting group number */
} ODBUSEGR;
```

## `cnc_rd1tlifedata`

Signature (verbatim):

```c
/* read tool life management data(tool data1) */
FWLIBAPI short WINAPI cnc_rd1tlifedata( unsigned short, short, short, IODBTD * ) ;
```

Referenced struct/type names: `IODBTD`

- `IODBTD`:

```c
typedef struct iodbtd {
    short   datano;     /* tool group number */
    short   type;       /* tool using number */
    long    tool_num;   /* tool number */
    long    h_code;     /* H code */
    long    d_code;     /* D code */
    long    tool_inf;   /* tool information */
} IODBTD;
```

## `cnc_rdalmmsg`

Signature (verbatim):

```c
/* read alarm message */
FWLIBAPI short WINAPI cnc_rdalmmsg( unsigned short, short, short *, ODBALMMSG * ) ;
```

Referenced struct/type names: `ODBALMMSG`

- `ODBALMMSG`:

```c
typedef struct odbalmmsg {
    long    alm_no;
    short   type;
    short   axis;
    short   dummy;
    short   msg_len;
    char    alm_msg[32];
} ODBALMMSG ;
```

## `cnc_rdalmmsg2`

Signature (verbatim):

```c
/* read alarm message */
FWLIBAPI short WINAPI cnc_rdalmmsg2( unsigned short, short, short *, ODBALMMSG2 * ) ;
```

Referenced struct/type names: `ODBALMMSG2`

- `ODBALMMSG2`:

```c
typedef struct odbalmmsg2 {
    long    alm_no;
    short   type;
    short   axis;
    short   dummy;
    short   msg_len;
    char    alm_msg[64];
} ODBALMMSG2 ;
```

## `cnc_rdtdiseltool`

Signature (verbatim):

```c
/* cnc_rdtdiseltool:read selected tool infomation */
FWLIBAPI short WINAPI cnc_rdtdiseltool(unsigned short, long, long *, long *);
```

No referenced user-defined types in arg list.

## `cnc_rdtltool`

Signature (verbatim):

```c
/* read tool life management data (tool data1) */
FWLIBAPI short WINAPI cnc_rdtltool( unsigned short, long, long, short *, IODBTLTOOL * ) ;
```

Referenced struct/type names: `IODBTLTOOL`

- `IODBTLTOOL`:

```c
typedef struct iodbtltool {
    long    tool_num;   /* tool number */
    long    h_code;     /* H code */
    long    d_code;     /* D code */
    long    tool_inf;   /* tool information */
} IODBTLTOOL;
```

## `cnc_rdtltoolnum`

**NOT FOUND in this header.**

Likely reasons: function not exposed by the FS30i processing DLL (`fwlib30i64.dll`) for the 0i-MF series, or the SDK uses a different name. Cross-check the FOCAS2 developer manual for an equivalent.

## `cnc_rdtldata`

Signature (verbatim):

```c
/* read work zero point measurement TL value */
FWLIBAPI short WINAPI cnc_rdtldata( unsigned short, ODBTLDATA * ) ;
```

Referenced struct/type names: `ODBTLDATA`

- `ODBTLDATA`:

```c
typedef struct	tldata {
	long	tl;			/* tl data */
	long	tl_dp;		/* tl dp */
} ODBTLDATA ;
```

## `cnc_rdtoolinfo`

Signature (verbatim):

```c
/* read tool information */
FWLIBAPI short WINAPI cnc_rdtoolinfo( unsigned short, ODBPTLINF * ) ;
```

Referenced struct/type names: `ODBPTLINF`

- `ODBPTLINF`:

```c
typedef struct odbptlinf {
	short	tld_max;
	short	mlt_max;
	short	reserve;
	short	tld_size[16];
	short	mlt_size[16];
	short	reserves[16];
} ODBPTLINF ;
```

## `cnc_rdactivetool`

**NOT FOUND in this header.**

Likely reasons: function not exposed by the FS30i processing DLL (`fwlib30i64.dll`) for the 0i-MF series, or the SDK uses a different name. Cross-check the FOCAS2 developer manual for an equivalent.

## `cnc_rdmacro`

Signature (verbatim):

```c
/* read custom macro variable */
FWLIBAPI short WINAPI cnc_rdmacro( unsigned short, short, short, ODBM * ) ;
```

Referenced struct/type names: `ODBM`

- `ODBM`:

```c
typedef struct odbm {
    short   datano ;    /* variable number */
    short   dummy ;     /* dummy */
    long    mcr_val ;   /* macro variable */
    short   dec_val ;   /* decimal point */
} ODBM ;
```

## `cnc_rdmacror`

Signature (verbatim):

```c
/* read custom macro variables(area specified) */
FWLIBAPI short WINAPI cnc_rdmacror( unsigned short, short, short, short, IODBMR * ) ;
```

Referenced struct/type names: `IODBMR`

- `IODBMR`:

```c
typedef struct iodbmr {
    short   datano_s ;  /* start macro number */
    short   dummy ;     /* dummy */
    short   datano_e ;  /* end macro number */
    struct {
        long    mcr_val ;   /* macro variable */
        short   dec_val ;   /* decimal point */
    } data[5] ;
} IODBMR ;
```

## `cnc_rdtllife`

**NOT FOUND in this header.**

Likely reasons: function not exposed by the FS30i processing DLL (`fwlib30i64.dll`) for the 0i-MF series, or the SDK uses a different name. Cross-check the FOCAS2 developer manual for an equivalent.

## `cnc_rdtlinfo`

Signature (verbatim):

```c
/* read tool life management data */
FWLIBAPI short WINAPI cnc_rdtlinfo( unsigned short, ODBTLINFO * ) ;
```

Referenced struct/type names: `ODBTLINFO`

- `ODBTLINFO`:

```c
typedef struct odbtlinfo {
    long    max_group;  /* maximum number of tool groups */
    long    max_tool;   /* maximum number of tool within group */
    long    max_minute; /* maximum number of life count (minutes) */
    long    max_cycle;  /* maximum number of life count (cycles) */
} ODBTLINFO;
```

## `cnc_rdcurmgr`

**NOT FOUND in this header.**

Likely reasons: function not exposed by the FS30i processing DLL (`fwlib30i64.dll`) for the 0i-MF series, or the SDK uses a different name. Cross-check the FOCAS2 developer manual for an equivalent.

## `cnc_rdcurpot`

**NOT FOUND in this header.**

Likely reasons: function not exposed by the FS30i processing DLL (`fwlib30i64.dll`) for the 0i-MF series, or the SDK uses a different name. Cross-check the FOCAS2 developer manual for an equivalent.

## `cnc_rdpotinfo`

**NOT FOUND in this header.**

Likely reasons: function not exposed by the FS30i processing DLL (`fwlib30i64.dll`) for the 0i-MF series, or the SDK uses a different name. Cross-check the FOCAS2 developer manual for an equivalent.

## `cnc_rdmagsts`

**NOT FOUND in this header.**

Likely reasons: function not exposed by the FS30i processing DLL (`fwlib30i64.dll`) for the 0i-MF series, or the SDK uses a different name. Cross-check the FOCAS2 developer manual for an equivalent.

## `cnc_rdspmaint`

**NOT FOUND in this header.**

Likely reasons: function not exposed by the FS30i processing DLL (`fwlib30i64.dll`) for the 0i-MF series, or the SDK uses a different name. Cross-check the FOCAS2 developer manual for an equivalent.

## `cnc_rdspload`

Signature (verbatim):

```c
/* read load information of serial spindle */
FWLIBAPI short WINAPI cnc_rdspload( unsigned short, short, ODBSPN * ) ;
```

Referenced struct/type names: `ODBSPN`

- `ODBSPN`:

```c
typedef struct odbspn {
    short   datano;     /* spindle number */
    short   type;       /* dummy */
    short   data[MAX_SPINDLE];    /* spindle data */
} ODBSPN;
```

## `cnc_rdmgrptool`

**NOT FOUND in this header.**

Likely reasons: function not exposed by the FS30i processing DLL (`fwlib30i64.dll`) for the 0i-MF series, or the SDK uses a different name. Cross-check the FOCAS2 developer manual for an equivalent.

## `pmc_rdpmcrng`

Signature (verbatim):

```c
/* read PMC data(area specified) */
#if !defined (PMD)
FWLIBAPI short WINAPI pmc_rdpmcrng( unsigned short, short, short, unsigned short, unsigned short, unsigned short, IODBPMC * ) ;
```

Referenced struct/type names: `PMD`, `IODBPMC`

- `PMD`: typedef NOT FOUND in this header (may be a primitive alias, a Win32 typedef, or defined elsewhere)
- `IODBPMC`:

```c
typedef struct iodbpmc {
    short            type_a ;    /* PMC address type */
    short            type_d ;    /* PMC data type */
    unsigned short   datano_s ;  /* start PMC address */
    unsigned short   datano_e ;  /* end PMC address */
    union {
        char    cdata[5] ;  /* PMC data */
        short   idata[5] ;
        long    ldata[5] ;
        float   fdata[5] ;
        double  dfdata[5] ;
    } u ;
} IODBPMC ;
```

## `pmc_rdpmcinfo`

Signature (verbatim):

```c
/* read informations of PMC data */
FWLIBAPI short WINAPI pmc_rdpmcinfo( unsigned short, short, ODBPMCINF * ) ;
```

Referenced struct/type names: `ODBPMCINF`

- `ODBPMCINF`:

```c
typedef struct odbpmcinf {
    short   datano ;
    struct {
        char    pmc_adr ;
        char    adr_attr ;
        unsigned short  top_num ;
        unsigned short  last_num ;
    } info[64] ;
} ODBPMCINF ;
```

---

## Missing functions

These are the functions the session brief asked for that do not appear in this header. Each one needs a follow-up: either find an equivalent name, or accept that the 0i-MF doesn't support it and remove it from the v1 read set.

- `cnc_rdtltoolnum`
- `cnc_rdactivetool`
- `cnc_rdtllife`
- `cnc_rdcurmgr`
- `cnc_rdcurpot`
- `cnc_rdpotinfo`
- `cnc_rdmagsts`
- `cnc_rdspmaint`
- `cnc_rdmgrptool`
