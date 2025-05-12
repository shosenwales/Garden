from typing import Dict, List, Optional, Union
from enum import Enum
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

class QueryLanguage(Enum):
    SPL = "spl"
    LEQL = "leql"
    WQL = "wql"

@dataclass
class TimeRange:
    earliest: Optional[str] = None
    latest: Optional[str] = None

@dataclass
class SearchTerm:
    value: str
    field: Optional[str] = None
    operator: str = "="
    is_wildcard: bool = False
    is_grouped: bool = False

@dataclass
class SPLQuery:
    search_terms: List[Union[SearchTerm, str]]
    time_range: Optional[TimeRange] = None
    commands: List[Dict] = None
    subsearches: List[str] = None
    lookups: List[Dict] = None

class QueryConverter:
    def __init__(self):
        self.supported_languages = {
            QueryLanguage.SPL: self._parse_spl,
            QueryLanguage.LEQL: self._parse_leql,
            QueryLanguage.WQL: self._parse_wql
        }
        
        self.converters = {
            (QueryLanguage.SPL, QueryLanguage.LEQL): self._spl_to_leql,
            (QueryLanguage.SPL, QueryLanguage.WQL): self._spl_to_wql,
            (QueryLanguage.LEQL, QueryLanguage.SPL): self._leql_to_spl,
            (QueryLanguage.LEQL, QueryLanguage.WQL): self._leql_to_wql,
            (QueryLanguage.WQL, QueryLanguage.SPL): self._wql_to_spl,
            (QueryLanguage.WQL, QueryLanguage.LEQL): self._wql_to_leql
        }

    def convert_query(self, query: str, source_lang: QueryLanguage, target_lang: QueryLanguage) -> str:
        """
        Convert a query from one language to another.
        
        Args:
            query (str): The input query to convert
            source_lang (QueryLanguage): The source query language
            target_lang (QueryLanguage): The target query language
            
        Returns:
            str: The converted query
        """
        if source_lang == target_lang:
            return query
            
        converter = self.converters.get((source_lang, target_lang))
        if not converter:
            raise ValueError(f"Conversion from {source_lang.value} to {target_lang.value} is not supported")
        
        # Debug logging
        print(f"Converting from {source_lang.value} to {target_lang.value}")
        print(f"Input query: {query}")
        
        try:
            result = converter(query)
            print(f"Conversion result: {result}")
            return result
        except Exception as e:
            print(f"Conversion error: {str(e)}")
            raise

    def convert_to_all_languages(self, query: str, source_lang: QueryLanguage) -> Dict[str, str]:
        """
        Convert a query to all supported languages.
        
        Args:
            query (str): The input query to convert
            source_lang (QueryLanguage): The source query language
            
        Returns:
            Dict[str, str]: Dictionary mapping target languages to converted queries
        """
        results = {}
        for target_lang in QueryLanguage:
            if target_lang != source_lang:
                try:
                    converted = self.convert_query(query, source_lang, target_lang)
                    results[target_lang.value] = converted
                except Exception as e:
                    results[target_lang.value] = f"Error: {str(e)}"
        return results

    def _parse_spl(self, query: str) -> SPLQuery:
        """
        Parse a Splunk SPL query into an intermediate representation.
        
        Args:
            query (str): The SPL query to parse
            
        Returns:
            SPLQuery: Parsed query representation
        """
        # Initialize components
        search_terms = []
        time_range = TimeRange()
        commands = []
        subsearches = []
        lookups = []
        
        # Split query into parts
        parts = query.split('|')
        search_part = parts[0].strip()
        
        # Parse time modifiers
        time_pattern = r'(earliest|latest)=([^\s]+)'
        time_matches = re.finditer(time_pattern, search_part)
        for match in time_matches:
            modifier, value = match.groups()
            if modifier == 'earliest':
                time_range.earliest = value
            else:
                time_range.latest = value
            search_part = search_part.replace(match.group(), '').strip()
        
        # Parse subsearches
        subsearch_pattern = r'\[(.*?)\]'
        subsearch_matches = re.finditer(subsearch_pattern, search_part)
        for match in subsearch_matches:
            subsearches.append(match.group(1))
            search_part = search_part.replace(match.group(), '').strip()
        
        # Parse search terms with boolean operators
        # First split by OR
        or_parts = search_part.split(' OR ')
        for or_part in or_parts:
            # Then split by AND
            and_parts = or_part.split(' AND ')
            for and_part in and_parts:
                # Handle field=value pairs with various operators
                field_pattern = r'([a-zA-Z0-9_\.]+)\s*(=|!=|>|<|>=|<=)\s*([^\s]+)'
                field_matches = re.finditer(field_pattern, and_part)
                for match in field_matches:
                    field, operator, value = match.groups()
                    # Handle quoted values
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    search_terms.append(SearchTerm(field=field, value=value, operator=operator))
                    and_part = and_part.replace(match.group(), '').strip()
                
                # Handle wildcard fields
                wildcard_pattern = r'([a-zA-Z0-9_\.]*\*[a-zA-Z0-9_\.]*)'
                wildcard_matches = re.finditer(wildcard_pattern, and_part)
                for match in wildcard_matches:
                    field = match.group()
                    search_terms.append(SearchTerm(field=field, value="*", operator="=", is_wildcard=True))
                    and_part = and_part.replace(match.group(), '').strip()
                
                # Handle remaining search terms
                remaining_terms = [term.strip() for term in and_part.split() if term.strip()]
                search_terms.extend(remaining_terms)
        
        # Parse commands
        for part in parts[1:]:
            cmd_parts = part.strip().split()
            if cmd_parts:
                cmd = {
                    'name': cmd_parts[0],
                    'args': []
                }
                
                # Handle BY clauses
                if cmd_parts[0].upper() == 'BY':
                    cmd['args'].append('by')
                    cmd_parts = cmd_parts[1:]
                    # Collect all fields after BY
                    by_fields = []
                    for cmd_part in cmd_parts:
                        if cmd_part not in ['|', 'BY']:
                            by_fields.append(cmd_part)
                    cmd['args'].extend(by_fields)
                
                # Handle AS clauses (field aliases)
                elif cmd_parts[0].upper() == 'AS':
                    cmd['args'].append('as')
                    cmd_parts = cmd_parts[1:]
                    if len(cmd_parts) > 0:
                        cmd['args'].append(cmd_parts[0])
                    cmd_parts = cmd_parts[1:]
                
                # Handle lookup commands
                elif cmd_parts[0].upper() == 'LOOKUP':
                    lookup = {'type': 'lookup', 'args': []}
                    cmd_parts = cmd_parts[1:]
                    while len(cmd_parts) > 0 and cmd_parts[0] not in ['|', 'AS']:
                        lookup['args'].append(cmd_parts[0])
                        cmd_parts = cmd_parts[1:]
                    lookups.append(lookup)
                
                else:
                    cmd['args'].extend(cmd_parts)
                
                commands.append(cmd)
        
        return SPLQuery(
            search_terms=search_terms,
            time_range=time_range if time_range.earliest or time_range.latest else None,
            commands=commands if commands else None,
            subsearches=subsearches if subsearches else None,
            lookups=lookups if lookups else None
        )

    def _parse_leql(self, query: str) -> Dict:
        """
        Parse a Rapid7 LEQL query into an intermediate representation.
        
        Args:
            query (str): The LEQL query to parse
            
        Returns:
            Dict: Parsed query representation
        """
        print(f"Parsing LEQL query: {query}")  # Debug logging
        
        # Initialize components
        search_terms = []
        time_range = TimeRange()
        commands = []
        
        # Handle where clause
        if 'where(' in query:
            where_start = query.find('where(')
            where_end = query.find(')', where_start)
            if where_end != -1:
                where_clause = query[where_start + 6:where_end]
                print(f"Found where clause: {where_clause}")  # Debug logging
                
                # Parse conditions
                if 'ICONTAINS' in where_clause:
                    field, value = where_clause.split('ICONTAINS', 1)
                    field = field.strip()
                    value = value.strip().strip('"\'')
                    search_terms.append(SearchTerm(field=field, value=value, operator='icontains'))
                    print(f"Added search term: {field} ICONTAINS {value}")  # Debug logging
        
        # Handle groupby clause
        if 'groupby(' in query:
            groupby_start = query.find('groupby(')
            groupby_end = query.find(')', groupby_start)
            if groupby_end != -1:
                groupby_clause = query[groupby_start + 8:groupby_end]
                print(f"Found groupby clause: {groupby_clause}")  # Debug logging
                commands.append({
                    'name': 'groupby',
                    'args': [groupby_clause.strip()]
                })
        
        result = {
            'search_terms': search_terms,
            'time_range': time_range if time_range.earliest or time_range.latest else None,
            'commands': commands if commands else None
        }
        
        print(f"Parsed result: {result}")  # Debug logging
        return result

    def _parse_wql(self, query: str) -> Dict:
        """
        Parse a Wazuh WQL query into an intermediate representation.
        
        Args:
            query (str): The WQL query to parse
            
        Returns:
            Dict: Parsed query representation
        """
        # Initialize components
        search_terms = []
        time_range = TimeRange()
        
        # Split query into parts by semicolon (WQL's AND operator)
        parts = query.split(';')
        
        for part in parts:
            part = part.strip()
            
            # Handle time range
            if part.startswith('time:'):
                time_parts = part[5:].strip().split(';')
                for time_part in time_parts:
                    if '>=' in time_part:
                        time_range.earliest = time_part.split('>=')[1].strip()
                    elif '<=' in time_part:
                        time_range.latest = time_part.split('<=')[1].strip()
                    elif '>' in time_part:
                        time_range.earliest = time_part.split('>')[1].strip()
                    elif '<' in time_part:
                        time_range.latest = time_part.split('<')[1].strip()
            
            # Handle field=value pairs
            elif '=' in part:
                field, value = part.split('=', 1)
                search_terms.append(SearchTerm(field=field.strip(), value=value.strip()))
            
            # Handle field!=value pairs
            elif '!=' in part:
                field, value = part.split('!=', 1)
                search_terms.append(SearchTerm(field=field.strip(), value=value.strip(), operator='!='))
            
            # Handle field>value pairs
            elif '>' in part and not '>=' in part:
                field, value = part.split('>', 1)
                search_terms.append(SearchTerm(field=field.strip(), value=value.strip(), operator='>'))
            
            # Handle field<value pairs
            elif '<' in part and not '<=' in part:
                field, value = part.split('<', 1)
                search_terms.append(SearchTerm(field=field.strip(), value=value.strip(), operator='<'))
            
            # Handle field>=value pairs
            elif '>=' in part:
                field, value = part.split('>=', 1)
                search_terms.append(SearchTerm(field=field.strip(), value=value.strip(), operator='>='))
            
            # Handle field<=value pairs
            elif '<=' in part:
                field, value = part.split('<=', 1)
                search_terms.append(SearchTerm(field=field.strip(), value=value.strip(), operator='<='))
            
            # Handle like operator (~)
            elif '~' in part:
                field, value = part.split('~', 1)
                search_terms.append(SearchTerm(field=field.strip(), value=value.strip(), operator='~'))
            
            # Handle grouped expressions
            elif part.startswith('(') and part.endswith(')'):
                inner_query = part[1:-1].strip()
                inner_terms = self._parse_wql(inner_query)
                for term in inner_terms['search_terms']:
                    term.is_grouped = True
                    search_terms.append(term)
        
        return {
            'search_terms': search_terms,
            'time_range': time_range if time_range.earliest or time_range.latest else None
        }

    def _spl_to_leql(self, query: str) -> str:
        """
        Convert SPL query to LEQL.
        
        Args:
            query (str): The SPL query to convert
            
        Returns:
            str: The converted LEQL query
        """
        parsed = self._parse_spl(query)
        leql_parts = []
        
        # Handle time range
        if parsed.time_range:
            if parsed.time_range.earliest:
                # Convert SPL time modifiers to LEQL format
                time_value = parsed.time_range.earliest
                if time_value.startswith('-'):
                    time_value = time_value[1:]  # Remove the minus sign
                leql_parts.append(f"from {time_value}")
            if parsed.time_range.latest:
                leql_parts.append(f"to {parsed.time_range.latest}")
        
        # Handle search terms
        where_clauses = []
        for term in parsed.search_terms:
            if isinstance(term, SearchTerm):
                if term.field:
                    # Handle field=value pairs
                    if term.operator == "=":
                        where_clauses.append(f"{term.field} = '{term.value}'")
                    elif term.operator == "!=":
                        where_clauses.append(f"{term.field} != '{term.value}'")
                    elif term.operator == ">":
                        where_clauses.append(f"{term.field} > '{term.value}'")
                    elif term.operator == "<":
                        where_clauses.append(f"{term.field} < '{term.value}'")
                    elif term.operator == ">=":
                        where_clauses.append(f"{term.field} >= '{term.value}'")
                    elif term.operator == "<=":
                        where_clauses.append(f"{term.field} <= '{term.value}'")
                else:
                    # Handle free text search
                    where_clauses.append(f"message contains '{term.value}'")
            else:
                # Handle free text search terms
                where_clauses.append(f"message contains '{term}'")
        
        if where_clauses:
            leql_parts.append(f"where ({' AND '.join(where_clauses)})")
        
        # Handle commands
        if parsed.commands:
            for cmd in parsed.commands:
                if cmd['name'] == 'stats':
                    if 'count' in cmd['args']:
                        # Handle stats count
                        leql_parts.append("calculate(count)")
                        
                        # Handle groupby
                        if 'by' in cmd['args']:
                            by_index = cmd['args'].index('by')
                            if by_index + 1 < len(cmd['args']):
                                group_by_fields = cmd['args'][by_index + 1:]
                                leql_parts.append(f"groupby({', '.join(group_by_fields)})")
                
                elif cmd['name'] == 'table':
                    # Handle table command by selecting specific fields
                    fields = cmd['args']
                    if fields:
                        select_clause = f"select ({', '.join(fields)})"
                        leql_parts.append(select_clause)
                
                elif cmd['name'] == 'sort':
                    # Handle sort command
                    if len(cmd['args']) >= 2:
                        field = cmd['args'][0]
                        direction = cmd['args'][1].lower()
                        sort_direction = "desc" if direction == "desc" else "asc"
                        leql_parts.append(f"sort({sort_direction})")
                
                elif cmd['name'] == 'timeslice':
                    # Handle timeslice command
                    if len(cmd['args']) >= 1:
                        interval = cmd['args'][0]
                        leql_parts.append(f"timeslice({interval})")
                
                elif cmd['name'] == 'stats' and 'avg' in cmd['args']:
                    # Handle average calculation
                    field_index = cmd['args'].index('avg') + 1
                    if field_index < len(cmd['args']):
                        field = cmd['args'][field_index]
                        leql_parts.append(f"calculate(average:{field})")
                
                elif cmd['name'] == 'stats' and 'sum' in cmd['args']:
                    # Handle sum calculation
                    field_index = cmd['args'].index('sum') + 1
                    if field_index < len(cmd['args']):
                        field = cmd['args'][field_index]
                        leql_parts.append(f"calculate(sum:{field})")
                
                elif cmd['name'] == 'stats' and 'min' in cmd['args']:
                    # Handle min calculation
                    field_index = cmd['args'].index('min') + 1
                    if field_index < len(cmd['args']):
                        field = cmd['args'][field_index]
                        leql_parts.append(f"calculate(min:{field})")
                
                elif cmd['name'] == 'stats' and 'max' in cmd['args']:
                    # Handle max calculation
                    field_index = cmd['args'].index('max') + 1
                    if field_index < len(cmd['args']):
                        field = cmd['args'][field_index]
                        leql_parts.append(f"calculate(max:{field})")
        
        return " ".join(leql_parts)

    def _spl_to_wql(self, query: str) -> str:
        """
        Convert SPL query to WQL.
        
        Args:
            query (str): The SPL query to convert
            
        Returns:
            str: The converted WQL query
        """
        parsed = self._parse_spl(query)
        wql_parts = []
        
        # Handle time range
        if parsed.time_range:
            time_clause = []
            if parsed.time_range.earliest:
                time_clause.append(f"time>={parsed.time_range.earliest}")
            if parsed.time_range.latest:
                time_clause.append(f"time<={parsed.time_range.latest}")
            if time_clause:
                wql_parts.append(f"time: {';'.join(time_clause)}")
        
        # Handle search terms
        search_clauses = []
        for term in parsed.search_terms:
            if isinstance(term, SearchTerm):
                if term.field:
                    # Handle field=value pairs with operators
                    if term.operator == "=":
                        search_clauses.append(f"{term.field}={term.value}")
                    elif term.operator == "!=":
                        search_clauses.append(f"{term.field}!={term.value}")
                    elif term.operator == ">":
                        search_clauses.append(f"{term.field}>{term.value}")
                    elif term.operator == "<":
                        search_clauses.append(f"{term.field}<{term.value}")
                    elif term.operator == ">=":
                        search_clauses.append(f"{term.field}>={term.value}")
                    elif term.operator == "<=":
                        search_clauses.append(f"{term.field}<={term.value}")
                else:
                    # Handle free text search using like operator
                    search_clauses.append(f"message~{term.value}")
            else:
                # Handle free text search terms
                search_clauses.append(f"message~{term}")
        
        if search_clauses:
            wql_parts.append(";".join(search_clauses))
        
        # Handle grouping operators
        if len(wql_parts) > 1:
            wql_parts = [f"({part})" for part in wql_parts]
        
        # WQL doesn't support commands like SPL, so we'll ignore them
        # However, we can add a note about this limitation
        if parsed.commands:
            wql_parts.append("(Note: WQL does not support SPL commands)")
        
        return " ".join(wql_parts)

    def _leql_to_spl(self, query: str) -> str:
        """
        Convert LEQL query to SPL.
        
        Args:
            query (str): The LEQL query to convert
            
        Returns:
            str: The converted SPL query
        """
        print(f"Converting LEQL to SPL: {query}")  # Debug logging
        parsed = self._parse_leql(query)
        spl_parts = []
        
        # Handle search terms
        search_terms = []
        for term in parsed.get('search_terms', []):
            if term.operator.lower() == 'icontains':
                search_terms.append(f"{term.field}*{term.value}*")
        
        if search_terms:
            spl_parts.append(" ".join(search_terms))
        
        # Handle commands
        if parsed.get('commands'):
            for cmd in parsed['commands']:
                if cmd['name'] == 'groupby':
                    fields = cmd['args']
                    spl_parts.append(f"| stats count by {', '.join(fields)}")
        
        result = " ".join(spl_parts)
        print(f"SPL conversion result: {result}")  # Debug logging
        return result

    def _leql_to_wql(self, query: str) -> str:
        """
        Convert LEQL query to WQL.
        
        Args:
            query (str): The LEQL query to convert
            
        Returns:
            str: The converted WQL query
        """
        print(f"Converting LEQL to WQL: {query}")  # Debug logging
        parsed = self._parse_leql(query)
        wql_parts = []
        
        # Handle search terms
        search_clauses = []
        for term in parsed.get('search_terms', []):
            if term.operator.lower() == 'icontains':
                # WQL uses ~ for text search
                search_clauses.append(f"{term.field}~{term.value}")
        
        if search_clauses:
            wql_parts.append(";".join(search_clauses))
        
        # WQL doesn't support groupby directly, so we'll add a note
        if parsed.get('commands'):
            for cmd in parsed['commands']:
                if cmd['name'] == 'groupby':
                    wql_parts.append("(Note: WQL does not support grouping operations)")
        
        result = " ".join(wql_parts)
        print(f"WQL conversion result: {result}")  # Debug logging
        return result

    def _wql_to_spl(self, query: str) -> str:
        """Convert WQL query to SPL."""
        # TODO: Implement WQL to SPL conversion
        pass

    def _wql_to_leql(self, query: str) -> str:
        """Convert WQL query to LEQL."""
        # TODO: Implement WQL to LEQL conversion
        pass 