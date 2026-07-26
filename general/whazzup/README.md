# whazzup
Whazzup生成器。  

## 配置
```toml
[plugin.whazzup]
use_heading = 布尔值，是否使用航向角替换PBH
encoding = 字符串，客户端使用的编码如gbk又如utf-8
register_httpapi = 布尔值，是否向httpapi插件注册/whazzup.json接口
httpapi_require_auth = 布尔值，/whazzup.json接口是否需要鉴权
```

## 使用(开发)
```python3
from pyfsd.plugins.whazzup import generate_whazzup

whazzup_dict: dict = generate_whazzup(heading_instead_pbh=False)
whazzup_json: str = whazzup_json_string(heading_instead_pbh=False)
```
参数:  
heading\_instead\_pbh: 是否生成"heading"(航向)字段而非"pbh"字段(bool值)
```

## 示例数据
```json
{
    "pilot": [
        {
            "cid": "0000",
            "name": "realname",
            "callsign": "0000",
            "logon_time": "2026-07-26T14:52:10.0000000Z",
            "rating": 1,
            "last_updated": 1785079134,
            "latitude": 49.30472,
            "longitude": 8.45139,
            "altitude": 312,
            // using use_heading = true
            "heading": 0,
            // using use_heading = false
            "pbh": 0,
            "groundspeed": 0,
            "transponder": "2000",
            "flight_plan": {
                "flight_rules": "I",
                "aircraft": "B738/X",
                "departure": "ZSFZ",
                "arrival": "ZBAD",
                "alternate": "ZBAA",
                "cruise_tas": 100,
                "altitude": "FL070",
                "deptime": 114,
                "hrs_enroute_time": 11,
                "min_enroute_time": 45,
                "hrs_fuel_time": 14,
                "min_fuel_time": 19,
                "remarks": "/T/",
                "route": "ROUTE",
                "revision_id": 0
            },
            "aircraft_info": {
                "equipment": "B738",
                "airline": "CSN",
                "livery": "SWIFT_L1759A1787M78794"
            }
        }
    ],
    "controllers": [
        {
            "cid": "0000",
            "name": "realname",
            "callsign": "ZBAD_TWR",
            "logon_time": "2026-07-26T15:18:31.0000000Z",
            "rating": 12,
            "last_updated": 1785079120,
            "latitude": 39.50995,
            "longitude": 116.41092,
            "frequency": "118.375",
            "facility": 4,
            "visual_range": 50,
            "atis": [
                "atis goes here"
            ]
        }
    ],
    "general": {
        "version": 3,
        "reload": 1,
        "update": "20260726151856",
        "update_timestamp": "2026-07-26T15:18:56.6661020Z"
    }
}
```

### 关于pbh字段
可解析出俯仰角，侧滑角和航向角  
解析方法请看[X-Pilot源码](https://github.com/xpilot-project/xpilot/blob/b7a2375be88e8201c2c3fd8a353ace86f7ef49c3/client/src/fsd/pdu/pdu_base.cpp#L51-L82)
