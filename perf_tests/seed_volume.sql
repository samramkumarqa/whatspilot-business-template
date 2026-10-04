INSERT INTO customer_mapping(customer_phone,business_phone,customer_name)
 SELECT '+1888'||lpad(g::text,7,'0'), :'tonum', 'Customer '||g FROM generate_series(1,10000) g ON CONFLICT DO NOTHING;
INSERT INTO leads(customer_phone,business_id,status,lead_score,intent,buying_stage,sentiment,probability,priority)
 SELECT '+1888'||lpad(g::text,7,'0'),'loadtest-biz-1',(ARRAY['New','Contacted','Qualified','Proposal Sent','Closed Won','Closed Lost'])[1+g%6],g%100,'Pricing','Consideration','Positive',g%100,(ARRAY['Low','Medium','High'])[1+g%3] FROM generate_series(1,10000) g ON CONFLICT DO NOTHING;
INSERT INTO conversations(phone,role,content,sender,created_at)
 SELECT 'loadtest-biz-1:+1888'||lpad((1+g%10000)::text,7,'0'),(ARRAY['user','assistant'])[1+g%2],'Message number '||g||' lorem ipsum dolor sit amet',(ARRAY['customer','ai'])[1+g%2], now()-(g%90||' days')::interval FROM generate_series(1,100000) g;
INSERT INTO opportunities(customer_phone,business_id,opportunity_type,confidence,reason,estimated_value,status)
 SELECT '+1888'||lpad(g::text,7,'0'),'loadtest-biz-1','Upsell',g%100,'x',(g%50)*1000,'Open' FROM generate_series(1,10000) g;
INSERT INTO reminders(customer_phone,business_id,reminder_text,due_date,status)
 SELECT '+1888'||lpad(g::text,7,'0'),'loadtest-biz-1','Follow up',to_char(current_date+((g%30)-10),'YYYY-MM-DD'),'Pending' FROM generate_series(1,10000) g;
INSERT INTO ai_activity(customer_phone,business_id,activity_type,title,details)
 SELECT '+1888'||lpad((1+g%10000)::text,7,'0'),'loadtest-biz-1','Note','t','d' FROM generate_series(1,30000) g;
INSERT INTO unread_messages(conversation_id,unread_count) SELECT 'loadtest-biz-1:+1888'||lpad(g::text,7,'0'),g%5 FROM generate_series(1,10000) g ON CONFLICT DO NOTHING;
